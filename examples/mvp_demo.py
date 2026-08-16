"""Run the deterministic MandateLab MVP flow against the shared fixtures.

This is a composition harness, not a new policy layer. Every authorization
decision remains inside ``mandatelab_engine`` and every execution guard remains
inside ``mandatelab_sandbox_executor``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for source_directory in (
    REPOSITORY_ROOT / "contracts" / "src",
    REPOSITORY_ROOT / "mandate_engine" / "src",
    REPOSITORY_ROOT / "sandbox_executor" / "src",
):
    if str(source_directory) not in sys.path:
        sys.path.insert(0, str(source_directory))

from mandatelab_contracts import (
    AuthorizationPolicy,
    BuyerPreferenceProfile,
    CartSnapshot,
    ConstraintKind,
    ConstraintOperator,
    HardConstraint,
    HumanApproval,
    Mandate,
    MandateSource,
    Money,
    PurchaseIntent,
    TransactionCandidate,
)
from mandatelab_engine import (
    compute_cart_fingerprint,
    evaluate_candidate,
    parse_mandate,
    rank_candidates,
    validate_precheckout,
)
from mandatelab_sandbox_executor import InMemorySandboxExecutor


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
CATALOG_PATH = (
    REPOSITORY_ROOT
    / "mandate_engine"
    / "fixtures"
    / "headphones_catalog.json"
)
MAYA_PROFILE_PATH = (
    REPOSITORY_ROOT
    / "contracts"
    / "examples"
    / "buyer_preference_profile.json"
)
THEO_PROFILE_PATH = (
    REPOSITORY_ROOT
    / "mandate_engine"
    / "fixtures"
    / "existing_buyer_profile.json"
)


def _load_profile(path: Path) -> BuyerPreferenceProfile:
    return BuyerPreferenceProfile.model_validate_json(path.read_text())


def _load_catalog() -> list[TransactionCandidate]:
    payload = json.loads(CATALOG_PATH.read_text())
    return [
        TransactionCandidate.model_validate(candidate)
        for candidate in payload["candidates"]
    ]


def _authorization(autonomous: str, maximum: str) -> AuthorizationPolicy:
    return AuthorizationPolicy(
        autonomous_spend_limit=Money(amount=autonomous),
        maximum_authorized_total=Money(amount=maximum),
    )


def _new_only_constraint() -> HardConstraint:
    return HardConstraint(
        constraint_id="new-headphones-only",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW"],
        source=MandateSource.CURRENT_EXPLICIT,
    )


def _intent(
    profile: BuyerPreferenceProfile,
    *,
    intent_id: str,
    autonomous: str,
    maximum: str,
    require_new: bool = False,
) -> PurchaseIntent:
    return PurchaseIntent(
        intent_id=intent_id,
        buyer_id=profile.buyer_id,
        raw_text="Buy noise-cancelling headphones",
        goal="Buy noise-cancelling headphones",
        category="headphones",
        hard_constraints=(
            [_new_only_constraint()] if require_new else []
        ),
        authorization=_authorization(autonomous, maximum),
        created_at=NOW,
    )


def _cart(
    candidate: TransactionCandidate,
    mandate: Mandate,
    *,
    cart_id: str,
) -> CartSnapshot:
    fingerprint = compute_cart_fingerprint(
        candidate, mandate.authorization.material_change_fields
    )
    return CartSnapshot.model_validate(
        {
            **candidate.model_dump(),
            "cart_id": cart_id,
            "cart_fingerprint": fingerprint,
        }
    )


def _warning_codes(warnings: list[str]) -> list[str]:
    return [warning.partition(":")[0] for warning in warnings]


def run_demo() -> dict[str, Any]:
    """Run the MVP evaluation scenarios and return a JSON-safe summary."""

    catalog = _load_catalog()
    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in catalog
    }
    maya = _load_profile(MAYA_PROFILE_PATH)
    theo = _load_profile(THEO_PROFILE_PATH)

    maya_comparison_mandate = parse_mandate(
        _intent(
            maya,
            intent_id="intent-maya-comparison",
            autonomous="600",
            maximum="600",
        ),
        maya,
        mandate_id="mandate-maya-comparison",
    )
    theo_comparison_mandate = parse_mandate(
        _intent(
            theo,
            intent_id="intent-theo-comparison",
            autonomous="600",
            maximum="600",
        ),
        theo,
        mandate_id="mandate-theo-comparison",
    )
    maya_ranking = rank_candidates(
        catalog, maya_comparison_mandate, maya
    )
    theo_ranking = rank_candidates(
        catalog, theo_comparison_mandate, theo
    )

    autonomous_mandate = parse_mandate(
        _intent(
            maya,
            intent_id="intent-autonomous",
            autonomous="250",
            maximum="300",
            require_new=True,
        ),
        maya,
        mandate_id="mandate-autonomous",
    )
    rejected_candidate = candidates_by_id["catalog-sony-xm4-silver"]
    blocked = evaluate_candidate(rejected_candidate, autonomous_mandate)
    if blocked.replan_instruction is None:
        raise RuntimeError("blocked demo candidate did not produce replanning feedback")

    excluded_ids = set(blocked.replan_instruction.exclude_candidate_ids)
    replanned_ranking = rank_candidates(
        [
            candidate
            for candidate in catalog
            if candidate.candidate_id not in excluded_ids
        ],
        autonomous_mandate,
        maya,
    )
    selected = replanned_ranking[0]
    selected_decision = evaluate_candidate(
        selected.candidate, autonomous_mandate
    )
    autonomous_cart = _cart(
        selected.candidate,
        autonomous_mandate,
        cart_id="cart-autonomous",
    )
    autonomous_precheckout = validate_precheckout(
        autonomous_cart,
        autonomous_mandate,
        evaluated_at=NOW,
    )
    autonomous_executor = InMemorySandboxExecutor()
    autonomous_outcome = autonomous_executor.execute(
        autonomous_cart,
        autonomous_precheckout,
        occurred_at=NOW,
        transaction_id="sandbox-transaction-autonomous",
    )

    changed_cart = CartSnapshot.model_validate(
        {
            **autonomous_cart.model_dump(),
            "final_landed_price": Money(
                amount=(
                    autonomous_cart.final_landed_price.amount
                    + Decimal("10")
                )
            ),
        }
    )
    changed_cart_decision = validate_precheckout(
        changed_cart,
        autonomous_mandate,
        evaluated_at=NOW,
    )

    review_mandate = parse_mandate(
        _intent(
            maya,
            intent_id="intent-human-review",
            autonomous="100",
            maximum="300",
            require_new=True,
        ),
        maya,
        mandate_id="mandate-human-review",
    )
    review_ranking = rank_candidates(catalog, review_mandate, maya)
    review_cart = _cart(
        review_ranking[0].candidate,
        review_mandate,
        cart_id="cart-human-review",
    )
    before_approval = validate_precheckout(
        review_cart,
        review_mandate,
        evaluated_at=NOW,
    )
    approval = HumanApproval(
        approval_id="approval-human-review",
        mandate_id=review_mandate.mandate_id,
        mandate_version=review_mandate.version,
        cart_id=review_cart.cart_id,
        cart_fingerprint=review_cart.cart_fingerprint,
        approver_id=maya.buyer_id,
        approved_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    after_approval = validate_precheckout(
        review_cart,
        review_mandate,
        approval,
        evaluated_at=NOW,
    )
    review_executor = InMemorySandboxExecutor()
    approved_outcome = review_executor.execute(
        review_cart,
        after_approval,
        occurred_at=NOW,
        transaction_id="sandbox-transaction-human-approved",
    )

    return {
        "buyer_specific_ranking": {
            "maya_top_candidate": maya_ranking[0].candidate.candidate_id,
            "maya_score": str(maya_ranking[0].explanation.total_score),
            "theo_top_candidate": theo_ranking[0].candidate.candidate_id,
            "theo_score": str(theo_ranking[0].explanation.total_score),
        },
        "blocked_and_replanned": {
            "blocked_candidate": rejected_candidate.candidate_id,
            "initial_decision": blocked.decision.value,
            "reason_codes": blocked.replan_instruction.reason_codes,
            "excluded_candidate_ids": sorted(excluded_ids),
            "selected_candidate": selected.candidate.candidate_id,
            "selected_decision": selected_decision.decision.value,
            "ranking_summary": selected.explanation.summary,
        },
        "autonomous_checkout": {
            "precheckout_decision": autonomous_precheckout.decision.value,
            "outcome": autonomous_outcome.status.value,
            "transaction_id": autonomous_outcome.transaction_id,
        },
        "human_approval": {
            "before_approval": before_approval.decision.value,
            "after_approval": after_approval.decision.value,
            "warning_codes": _warning_codes(after_approval.warnings),
            "outcome": approved_outcome.status.value,
        },
        "changed_cart": {
            "decision": changed_cart_decision.decision.value,
            "warning_codes": _warning_codes(changed_cart_decision.warnings),
        },
    }


def main() -> None:
    print(json.dumps(run_demo(), indent=2))


if __name__ == "__main__":
    main()
