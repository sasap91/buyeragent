from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mandatelab_contracts import BuyerPreferenceProfile
from user_profile import server
from user_profile.contract import ColdStartProfileBuilder, ColdStartProfileInput


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)


def profile() -> BuyerPreferenceProfile:
    return ColdStartProfileBuilder().build_profile(
        ColdStartProfileInput(
            buyer_id="cold-start-demo",
            category="*",
            price_sensitivity=None,
            quality_importance=None,
            brand_scores={},
            confidence=0,
            created_at=NOW,
        )
    )


def client() -> TestClient:
    app = FastAPI()
    app.include_router(server.router)
    return TestClient(app)


def test_existing_frontend_payload_receives_shared_profile(
    monkeypatch,
) -> None:
    snapshot = server.ModelUpdateResponse(
        weights=[server.WeightRow(name="intercept", value=0.0)],
        plots=server.PlotSnapshot(
            quality_price="png-one",
            price_sustainability="png-two",
        ),
        profile=profile(),
    )
    monkeypatch.setattr(
        server, "build_update_snapshot", lambda request: snapshot
    )

    response = client().post(
        "/api/update",
        json={
            "remaining_ids": ["sony_xm5"],
            "rejected_ids": ["budget_headphones"],
        },
    )

    assert response.status_code == 200
    assert response.json()["weights"][0]["name"] == "intercept"
    restored = BuyerPreferenceProfile.model_validate(
        response.json()["profile"]
    )
    assert restored.buyer_id == "cold-start-demo"
    assert restored.category == "*"


def test_request_rejects_overlapping_product_ids() -> None:
    response = client().post(
        "/api/update",
        json={"remaining_ids": ["sony_xm5"], "rejected_ids": ["sony_xm5"]},
    )

    assert response.status_code == 422


def test_unknown_product_ids_fail_before_loading_scientific_model() -> None:
    response = client().post(
        "/api/update",
        json={"remaining_ids": ["not-in-catalog"], "rejected_ids": []},
    )

    assert response.status_code == 400
    assert "unknown product ids" in response.json()["detail"]
