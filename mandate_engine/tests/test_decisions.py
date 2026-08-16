from __future__ import annotations

from datetime import date, datetime, timezone

from mandatelab_contracts import (
    ApprovalRequirement,
    AuthorizationPolicy,
    CartSnapshot,
    ConstraintKind,
    ConstraintOperator,
    Decision,
    DecisionResult,
    HardConstraint,
    Mandate,
    MandateSource,
    Money,
    ProductCondition,
    TransactionCandidate,
)
from mandatelab_engine import (
    AUTONOMOUS_SPEND_LIMIT_EXCEEDED,
    FINAL_LANDED_PRICE_UNKNOWN,
    MATERIAL_AMBIGUITY,
    MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED,
    evaluate_candidate,
)


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def authorization(
    autonomous: str = "200", maximum: str = "250"
) -> AuthorizationPolicy:
    return AuthorizationPolicy(
        autonomous_spend_limit=Money(amount=autonomous),
        maximum_authorized_total=Money(amount=maximum),
    )


def mandate(**updates: object) -> Mandate:
    payload: dict[str, object] = {
        "mandate_id": "mandate-headphones-1",
        "version": 1,
        "buyer_id": "buyer-maya",
        "goal": "Buy noise-cancelling headphones",
        "category": "headphones",
        "authorization": authorization(),
        "created_at": NOW,
    }
    payload.update(updates)
    return Mandate.model_validate(payload)


def candidate(**updates: object) -> TransactionCandidate:
    payload: dict[str, object] = {
        "candidate_id": "candidate-sony-black",
        "product_id": "sony-wh-1000xm5",
        "variant_id": "black",
        "product_name": "Sony WH-1000XM5",
        "brand": "Sony",
        "condition": ProductCondition.NEW,
        "features": ["active-noise-cancelling", "bluetooth"],
        "merchant": "MandateMart",
        "final_landed_price": Money(amount="150"),
        "delivery_date": date(2026, 8, 19),
        "observed_at": NOW,
    }
    payload.update(updates)
    return TransactionCandidate.model_validate(payload)


def condition_rule(*, required: bool = True) -> HardConstraint:
    return HardConstraint(
        constraint_id="new-only",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW"],
        required=required,
        source=MandateSource.CURRENT_EXPLICIT,
    )


def test_approve_when_constraints_pass_and_spend_is_autonomous() -> None:
    result = evaluate_candidate(
        candidate(), mandate(hard_constraints=[condition_rule()])
    )

    assert result.decision is Decision.APPROVE
    assert result.approval_requirement is ApprovalRequirement.NONE
    assert result.violations == []
    assert result.warnings == []
    assert result.replan_instruction is None


def test_hard_constraint_failure_blocks_and_produces_replan_feedback() -> None:
    rule = condition_rule()

    result = evaluate_candidate(
        candidate(condition=ProductCondition.REFURBISHED),
        mandate(hard_constraints=[rule]),
    )

    assert result.decision is Decision.BLOCK
    assert result.violations[0].code == "ALLOWED_CONDITION_FAIL"
    assert result.violations[0].constraint_id == rule.constraint_id
    assert result.approval_requirement is ApprovalRequirement.NONE
    assert result.replan_instruction is not None
    assert result.replan_instruction.reason_codes == ["ALLOWED_CONDITION_FAIL"]
    assert result.replan_instruction.required_constraints == [rule]
    assert result.replan_instruction.exclude_candidate_ids == [
        "candidate-sony-black"
    ]


def test_required_unknown_constraint_data_requires_review() -> None:
    result = evaluate_candidate(
        candidate(condition=None), mandate(hard_constraints=[condition_rule()])
    )

    assert result.decision is Decision.REVIEW
    assert result.approval_requirement is ApprovalRequirement.HUMAN
    assert result.violations == []
    assert result.warnings[0].startswith("ALLOWED_CONDITION_UNKNOWN:")


def test_optional_unknown_constraint_warns_but_can_approve() -> None:
    result = evaluate_candidate(
        candidate(condition=None),
        mandate(hard_constraints=[condition_rule(required=False)]),
    )

    assert result.decision is Decision.APPROVE
    assert result.warnings[0].startswith("ALLOWED_CONDITION_UNKNOWN:")


def test_missing_final_price_requires_review_even_without_price_constraint() -> None:
    result = evaluate_candidate(candidate(final_landed_price=None), mandate())

    assert result.decision is Decision.REVIEW
    assert result.approval_requirement is ApprovalRequirement.HUMAN
    assert any(
        warning.startswith(FINAL_LANDED_PRICE_UNKNOWN)
        for warning in result.warnings
    )


def test_spend_above_autonomous_limit_requires_human_review() -> None:
    result = evaluate_candidate(
        candidate(final_landed_price=Money(amount="225")), mandate()
    )

    assert result.decision is Decision.REVIEW
    assert result.approval_requirement is ApprovalRequirement.HUMAN
    assert result.violations == []
    assert any(
        warning.startswith(AUTONOMOUS_SPEND_LIMIT_EXCEEDED)
        for warning in result.warnings
    )


def test_authorization_limits_are_inclusive() -> None:
    at_autonomous_limit = evaluate_candidate(
        candidate(final_landed_price=Money(amount="200")), mandate()
    )
    at_maximum_limit = evaluate_candidate(
        candidate(final_landed_price=Money(amount="250")), mandate()
    )

    assert at_autonomous_limit.decision is Decision.APPROVE
    assert at_maximum_limit.decision is Decision.REVIEW
    assert at_maximum_limit.violations == []


def test_spend_above_maximum_authority_blocks_and_requests_replanning() -> None:
    result = evaluate_candidate(
        candidate(final_landed_price=Money(amount="275")), mandate()
    )

    assert result.decision is Decision.BLOCK
    assert result.violations[0].code == MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED
    assert result.violations[0].expected == Money(amount="250")
    assert result.violations[0].actual == Money(amount="275")
    assert result.replan_instruction is not None
    assert result.replan_instruction.reason_codes == [
        MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED
    ]


def test_material_ambiguity_requires_review() -> None:
    result = evaluate_candidate(
        candidate(), mandate(material_ambiguities=["COLOR_NOT_SPECIFIED"])
    )

    assert result.decision is Decision.REVIEW
    assert result.approval_requirement is ApprovalRequirement.HUMAN
    assert result.warnings == [
        f"{MATERIAL_AMBIGUITY}: COLOR_NOT_SPECIFIED"
    ]


def test_block_takes_precedence_over_review_conditions() -> None:
    result = evaluate_candidate(
        candidate(
            condition=ProductCondition.USED,
            final_landed_price=Money(amount="275"),
        ),
        mandate(
            hard_constraints=[condition_rule()],
            material_ambiguities=["COLOR_NOT_SPECIFIED"],
        ),
    )

    assert result.decision is Decision.BLOCK
    assert {violation.code for violation in result.violations} == {
        "ALLOWED_CONDITION_FAIL",
        MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED,
    }
    assert result.approval_requirement is ApprovalRequirement.NONE


def test_known_failure_blocks_even_when_constraint_is_not_required() -> None:
    result = evaluate_candidate(
        candidate(condition=ProductCondition.USED),
        mandate(hard_constraints=[condition_rule(required=False)]),
    )

    assert result.decision is Decision.BLOCK


def test_cart_snapshot_identifiers_are_bound_into_decision() -> None:
    transaction_candidate = candidate()
    cart = CartSnapshot(
        **transaction_candidate.model_dump(),
        cart_id="cart-1",
        cart_fingerprint=FINGERPRINT,
    )

    result = evaluate_candidate(cart, mandate())

    assert result.decision is Decision.APPROVE
    assert result.cart_id == "cart-1"
    assert result.cart_fingerprint == FINGERPRINT


def test_decision_result_round_trips_and_has_deterministic_identity() -> None:
    result = evaluate_candidate(candidate(), mandate())

    assert result.decision_id == (
        "decision:mandate-headphones-1:1:candidate-sony-black"
    )
    assert result.evaluated_at == NOW
    assert DecisionResult.model_validate_json(result.model_dump_json()) == result
