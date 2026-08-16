import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from mandatelab_contracts import (
    ApprovalRequirement,
    AuthorizationPolicy,
    BuyerPreferenceProfile,
    CartSnapshot,
    ConstraintKind,
    ConstraintOperator,
    ConstraintResult,
    ConstraintStatus,
    Decision,
    DecisionResult,
    HardConstraint,
    HardRuleCandidate,
    HumanApproval,
    ImportanceLevel,
    Mandate,
    MandateSource,
    Money,
    PreferenceAttribute,
    PreferenceDirection,
    PreferenceSignal,
    PreferenceSource,
    ProductCondition,
    PurchaseIntent,
    RankingExplanation,
    ReplanInstruction,
    SoftPreference,
    TransactionCandidate,
    TransactionOutcome,
    TransactionOutcomeStatus,
)


EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "buyer_preference_profile.json"
)
NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def test_canonical_buyer_profile_example_round_trips() -> None:
    profile = BuyerPreferenceProfile.model_validate_json(
        EXAMPLE_PATH.read_text(encoding="utf-8")
    )

    assert profile.buyer_id == "buyer-maya"
    assert profile.price_sensitivity.value is ImportanceLevel.MEDIUM
    assert profile.price_sensitivity.numeric_weight == Decimal("0.55")
    assert profile.preferred_brands[0].source is PreferenceSource.COLD_START
    assert profile.hard_rule_candidates[0].requires_confirmation is True

    encoded = json.loads(profile.model_dump_json())
    assert encoded["price_sensitivity"]["numeric_weight"] == "0.55"
    assert encoded["created_at"] == "2026-08-16T17:00:00Z"
    assert BuyerPreferenceProfile.model_validate(encoded) == profile


def test_learned_preference_requires_source_and_confidence() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    del payload["quality_importance"]["source"]
    del payload["quality_importance"]["confidence"]

    with pytest.raises(ValidationError) as error:
        BuyerPreferenceProfile.model_validate(payload)

    fields = {item["loc"] for item in error.value.errors()}
    assert ("quality_importance", "source") in fields
    assert ("quality_importance", "confidence") in fields


def test_money_is_decimal_and_usd_only() -> None:
    money = Money.model_validate({"amount": "249.99", "currency": "USD"})

    assert money.amount == Decimal("249.99")
    assert json.loads(money.model_dump_json()) == {
        "amount": "249.99",
        "currency": "USD",
    }

    with pytest.raises(ValidationError):
        Money.model_validate({"amount": "249.99", "currency": "EUR"})


def test_missing_candidate_data_remains_explicitly_null() -> None:
    candidate = TransactionCandidate(
        candidate_id="candidate-1",
        product_id="headphones-1",
        product_name="Example Headphones",
        observed_at=NOW,
    )

    assert candidate.condition is None
    assert candidate.features is None
    assert candidate.final_landed_price is None
    assert candidate.delivery_date is None

    encoded = json.loads(candidate.model_dump_json())
    assert encoded["condition"] is None
    assert encoded["features"] is None
    assert encoded["final_landed_price"] is None
    assert encoded["delivery_date"] is None


def test_unknown_constraint_result_accepts_missing_actual_value() -> None:
    result = ConstraintResult(
        constraint_id="condition-new",
        status=ConstraintStatus.UNKNOWN,
        expected=["NEW"],
        actual=None,
        code="CONDITION_UNKNOWN",
        explanation="The product condition was not supplied.",
    )

    assert result.status is ConstraintStatus.UNKNOWN
    assert json.loads(result.model_dump_json())["actual"] is None


def test_authorization_maximum_cannot_be_below_autonomous_limit() -> None:
    with pytest.raises(ValidationError, match="maximum_authorized_total"):
        AuthorizationPolicy(
            autonomous_spend_limit=Money(amount="200"),
            maximum_authorized_total=Money(amount="199.99"),
        )


def test_profile_rejects_brand_conflict() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    payload["disliked_brands"] = [payload["preferred_brands"][0]]

    with pytest.raises(ValidationError, match="both preferred and disliked"):
        BuyerPreferenceProfile.model_validate(payload)


def test_shared_contracts_serialize_together() -> None:
    authorization = AuthorizationPolicy(
        autonomous_spend_limit=Money(amount="200"),
        maximum_authorized_total=Money(amount="250"),
    )
    max_price = HardConstraint(
        constraint_id="max-price",
        kind=ConstraintKind.MAX_LANDED_PRICE,
        operator=ConstraintOperator.LTE,
        expected=Money(amount="250"),
        source=MandateSource.CURRENT_EXPLICIT,
    )
    brand_preference = SoftPreference(
        preference_id="prefer-sony",
        attribute=PreferenceAttribute.BRAND,
        direction=PreferenceDirection.PREFER,
        preferred_value="Sony",
        weight="0.8",
        source=PreferenceSource.CURRENT_EXPLICIT,
        confidence="1",
    )
    intent = PurchaseIntent(
        intent_id="intent-1",
        buyer_id="buyer-maya",
        raw_text="Buy new noise-cancelling headphones under $250.",
        goal="Buy noise-cancelling headphones",
        category="headphones",
        hard_constraints=[max_price],
        soft_preferences=[brand_preference],
        authorization=authorization,
        created_at=NOW,
    )
    mandate = Mandate(
        mandate_id="mandate-1",
        buyer_id=intent.buyer_id,
        goal=intent.goal,
        category=intent.category,
        hard_constraints=intent.hard_constraints,
        soft_preferences=intent.soft_preferences,
        authorization=authorization,
        created_at=NOW,
    )
    candidate = TransactionCandidate(
        candidate_id="candidate-1",
        product_id="sony-xm5",
        variant_id="black",
        product_name="Sony WH-1000XM5",
        brand="Sony",
        condition=ProductCondition.NEW,
        features=["noise-cancelling"],
        merchant="Sandbox Store",
        item_price=Money(amount="190"),
        shipping=Money(amount="10"),
        fees=Money(amount="0"),
        final_landed_price=Money(amount="200"),
        delivery_date=date(2026, 8, 20),
        observed_at=NOW,
    )
    cart = CartSnapshot(
        **candidate.model_dump(),
        cart_id="cart-1",
        cart_fingerprint=FINGERPRINT,
    )
    constraint_result = ConstraintResult(
        constraint_id=max_price.constraint_id,
        status=ConstraintStatus.PASS,
        expected=max_price.expected,
        actual=cart.final_landed_price,
        code="MAX_PRICE_PASSED",
        explanation="Final landed price is within the mandate maximum.",
    )
    ranking = RankingExplanation(
        total_score="0.91",
        component_scores={PreferenceAttribute.BRAND: Decimal("0.95")},
        influential_preferences=[brand_preference.preference_id],
        summary="Sony preference was the strongest ranking signal.",
    )
    replan = ReplanInstruction(
        reason_codes=["CONDITION_NOT_ALLOWED"],
        required_constraints=[
            HardConstraint(
                constraint_id="new-only",
                kind=ConstraintKind.ALLOWED_CONDITION,
                operator=ConstraintOperator.IN,
                expected=["NEW"],
                source=MandateSource.CURRENT_EXPLICIT,
            )
        ],
        exclude_candidate_ids=["candidate-refurbished"],
        message="Search again for a new-condition product.",
    )
    decision = DecisionResult(
        decision_id="decision-1",
        decision=Decision.APPROVE,
        mandate_id=mandate.mandate_id,
        mandate_version=mandate.version,
        candidate_id=candidate.candidate_id,
        cart_id=cart.cart_id,
        cart_fingerprint=cart.cart_fingerprint,
        constraint_results=[constraint_result],
        ranking_explanation=ranking,
        approval_requirement=ApprovalRequirement.NONE,
        replan_instruction=replan,
        evaluated_at=NOW,
    )
    approval = HumanApproval(
        approval_id="approval-1",
        mandate_id=mandate.mandate_id,
        mandate_version=mandate.version,
        cart_id=cart.cart_id,
        cart_fingerprint=cart.cart_fingerprint,
        approver_id="buyer-maya",
        approved_at=NOW,
    )
    outcome = TransactionOutcome(
        outcome_id="outcome-1",
        status=TransactionOutcomeStatus.EXECUTED,
        cart_id=cart.cart_id,
        decision_id=decision.decision_id,
        transaction_id="sandbox-transaction-1",
        occurred_at=NOW,
    )
    rule_candidate = HardRuleCandidate(
        candidate_id="candidate-rule-1",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW"],
        source=PreferenceSource.COLD_START,
        confidence="0.9",
    )
    signal = PreferenceSignal[ImportanceLevel](
        value=ImportanceLevel.HIGH,
        numeric_weight="0.9",
        source=PreferenceSource.CATEGORY_HISTORY,
        confidence="0.8",
    )

    contracts = [
        intent,
        mandate,
        candidate,
        cart,
        decision,
        approval,
        outcome,
        rule_candidate,
        signal,
    ]
    for contract in contracts:
        encoded = contract.model_dump_json()
        assert contract.__class__.model_validate_json(encoded) == contract


def test_executed_outcome_requires_transaction_id() -> None:
    with pytest.raises(ValidationError, match="transaction_id"):
        TransactionOutcome(
            outcome_id="outcome-1",
            status=TransactionOutcomeStatus.EXECUTED,
            cart_id="cart-1",
            decision_id="decision-1",
            occurred_at=NOW,
        )
