from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from mandatelab_api import create_app
from mandatelab_contracts import (
    AuthorizationPolicy,
    BuyerPreferenceProfile,
    CartSnapshot,
    Mandate,
    Money,
    PurchaseIntent,
    TransactionCandidate,
)
from mandatelab_engine import compute_cart_fingerprint, parse_mandate


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = (
    REPOSITORY_ROOT
    / "contracts"
    / "examples"
    / "buyer_preference_profile.json"
)
CATALOG_PATH = (
    REPOSITORY_ROOT
    / "mandate_engine"
    / "fixtures"
    / "headphones_catalog.json"
)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def profile() -> BuyerPreferenceProfile:
    return BuyerPreferenceProfile.model_validate_json(PROFILE_PATH.read_text())


@pytest.fixture(scope="module")
def catalog() -> list[TransactionCandidate]:
    payload = json.loads(CATALOG_PATH.read_text())
    return [
        TransactionCandidate.model_validate(candidate)
        for candidate in payload["candidates"]
    ]


def intent(profile: BuyerPreferenceProfile) -> PurchaseIntent:
    return PurchaseIntent(
        intent_id="intent-api-headphones",
        buyer_id=profile.buyer_id,
        raw_text="Buy noise-cancelling headphones",
        goal="Buy noise-cancelling headphones",
        category="headphones",
        authorization=AuthorizationPolicy(
            autonomous_spend_limit=Money(amount="300"),
            maximum_authorized_total=Money(amount="600"),
        ),
        created_at=NOW,
    )


def mandate(profile: BuyerPreferenceProfile) -> Mandate:
    return parse_mandate(
        intent(profile), profile, mandate_id="mandate-api-headphones"
    )


def cart(candidate: TransactionCandidate, policy: Mandate) -> CartSnapshot:
    fingerprint = compute_cart_fingerprint(
        candidate, policy.authorization.material_change_fields
    )
    return CartSnapshot.model_validate(
        {
            **candidate.model_dump(),
            "cart_id": "cart-api-headphones",
            "cart_fingerprint": fingerprint,
        }
    )


def json_payload(**values: Any) -> dict[str, Any]:
    return jsonable_encoder(values)


def test_health_and_openapi_publish_all_versioned_routes(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/api/pairs",
        "/api/update",
        "/api/v1/health",
        "/api/v1/mandates",
        "/api/v1/rankings",
        "/api/v1/decisions",
        "/api/v1/precheckout",
        "/api/v1/sandbox/execute",
    }


def test_mandate_route_uses_shared_contracts(
    client: TestClient, profile: BuyerPreferenceProfile
) -> None:
    response = client.post(
        "/api/v1/mandates",
        json=json_payload(
            intent=intent(profile),
            profile=profile,
            mandate_id="mandate-via-api",
        ),
    )

    assert response.status_code == 200
    parsed = Mandate.model_validate(response.json())
    assert parsed.mandate_id == "mandate-via-api"
    assert parsed.buyer_id == profile.buyer_id
    assert parsed.authorization.maximum_authorized_total.amount == 600


def test_domain_identity_error_is_a_clear_bad_request(
    client: TestClient, profile: BuyerPreferenceProfile
) -> None:
    mismatched = intent(profile).model_copy(
        update={"buyer_id": "another-buyer"}
    )

    response = client.post(
        "/api/v1/mandates",
        json=json_payload(intent=mismatched, profile=profile),
    )

    assert response.status_code == 400
    assert "buyer_id must match" in response.json()["detail"]


def test_ranking_route_serializes_candidates_and_explanations(
    client: TestClient,
    profile: BuyerPreferenceProfile,
    catalog: list[TransactionCandidate],
) -> None:
    response = client.post(
        "/api/v1/rankings",
        json=json_payload(
            candidates=[
                candidate.model_dump(mode="json")
                for candidate in catalog
            ],
            mandate=mandate(profile),
            profile=profile,
        ),
    )

    assert response.status_code == 200
    ranking = response.json()
    assert ranking[0]["candidate"]["candidate_id"] == (
        "catalog-sony-xm4-silver"
    )
    assert ranking[0]["explanation"]["total_score"] == "0.8100"
    assert ranking[0]["explanation"]["summary"]


def test_decision_route_returns_review_for_unknown_price(
    client: TestClient,
    profile: BuyerPreferenceProfile,
    catalog: list[TransactionCandidate],
) -> None:
    mystery = next(
        candidate
        for candidate in catalog
        if candidate.candidate_id == "catalog-mystery-anc-black"
    )

    response = client.post(
        "/api/v1/decisions",
        json=json_payload(candidate=mystery, mandate=mandate(profile)),
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "REVIEW"
    assert response.json()["approval_requirement"] == "HUMAN"


def test_precheckout_detects_changed_material_data(
    client: TestClient,
    profile: BuyerPreferenceProfile,
    catalog: list[TransactionCandidate],
) -> None:
    policy = mandate(profile)
    original = cart(catalog[0], policy)
    changed = CartSnapshot.model_validate(
        {
            **original.model_dump(),
            "final_landed_price": Money(amount="239.99"),
        }
    )

    response = client.post(
        "/api/v1/precheckout",
        json=json_payload(
            cart=changed,
            mandate=policy,
            evaluated_at=NOW,
        ),
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "REVIEW"
    assert any(
        warning.startswith("CART_FINGERPRINT_MISMATCH")
        for warning in response.json()["warnings"]
    )


def test_sandbox_route_preserves_executor_idempotency(
    client: TestClient,
    profile: BuyerPreferenceProfile,
    catalog: list[TransactionCandidate],
) -> None:
    confirmed_profile = profile.model_copy(
        update={"hard_rule_candidates": []}
    )
    policy = mandate(confirmed_profile)
    final_cart = cart(catalog[0], policy)
    precheckout = client.post(
        "/api/v1/precheckout",
        json=json_payload(
            cart=final_cart,
            mandate=policy,
            evaluated_at=NOW,
        ),
    ).json()
    request = json_payload(
        cart=final_cart,
        decision=precheckout,
        occurred_at=NOW,
        transaction_id="sandbox-api-transaction",
    )

    first = client.post("/api/v1/sandbox/execute", json=request)
    second = client.post("/api/v1/sandbox/execute", json=request)

    assert first.status_code == 200
    assert first.json()["status"] == "EXECUTED"
    assert first.json()["transaction_id"] == "sandbox-api-transaction"
    assert second.json() == first.json()


def test_usd_only_validation_is_enforced_at_the_http_boundary(
    client: TestClient, profile: BuyerPreferenceProfile
) -> None:
    payload = json_payload(intent=intent(profile), profile=profile)
    payload["intent"]["authorization"]["autonomous_spend_limit"][
        "currency"
    ] = "EUR"

    response = client.post("/api/v1/mandates", json=payload)

    assert response.status_code == 422


def test_cold_start_pairs_route_returns_headphones_catalog(client: TestClient) -> None:
    response = client.get("/api/pairs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == "headphones"
    assert payload["demo_pair_count"] == 5
    assert len(payload["pairs"]) == 14
    first = payload["pairs"][0]
    assert {"pair_id", "tradeoff", "prompt", "left", "right"} <= set(first)
    assert first["left"]["condition"]
    assert first["left"]["delivery_days"] is not None
    assert first["left"]["return_window_days"] is not None


def test_cold_start_update_returns_a_buyer_preference_profile(
    client: TestClient,
) -> None:
    maya_path = (
        REPOSITORY_ROOT / "user_profile" / "fixtures" / "maya_comparisons.json"
    )
    payload = json.loads(maya_path.read_text(encoding="utf-8"))
    payload["include_model"] = False

    response = client.post("/api/update", json=payload)

    assert response.status_code == 200
    body = response.json()
    profile = BuyerPreferenceProfile.model_validate(body["profile"])
    assert profile.buyer_id == "buyer-maya"
    assert profile.category == "headphones"
    assert profile.quality_importance.value.value == "HIGH"
    assert profile.hard_rule_candidates
    assert body["weights"] == []
    assert body["plots"] is None


def test_cold_start_update_rejects_unknown_pairs(client: TestClient) -> None:
    response = client.post(
        "/api/update",
        json={
            "buyer_id": "buyer-maya",
            "include_model": False,
            "comparisons": [{"pair_id": "not-a-pair", "choice": "LEFT"}],
        },
    )
    assert response.status_code == 400


def test_cold_start_update_accepts_rejected_product_ids(client: TestClient) -> None:
    response = client.post(
        "/api/update",
        json={
            "buyer_id": "buyer-maya",
            "include_model": False,
            "rejected_product_ids": ["generic-anc-100"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    profile = BuyerPreferenceProfile.model_validate(body["profile"])
    assert profile.buyer_id == "buyer-maya"
    assert profile.category == "headphones"
    assert profile.quality_importance.value.value == "HIGH"
    assert profile.price_sensitivity.value.value == "LOW"


def test_cold_start_update_rejects_unknown_product_ids(client: TestClient) -> None:
    response = client.post(
        "/api/update",
        json={
            "buyer_id": "buyer-maya",
            "include_model": False,
            "rejected_product_ids": ["not-a-product"],
        },
    )
    assert response.status_code == 400
