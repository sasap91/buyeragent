from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mandatelab_contracts import (
    AuthorizationPolicy,
    BuyerPreferenceProfile,
    ConstraintKind,
    ConstraintOperator,
    HardConstraint,
    ImportanceLevel,
    Mandate,
    MandateSource,
    Money,
    PreferenceAttribute,
    PreferenceDirection,
    PreferenceSignal,
    PreferenceSource,
    PurchaseIntent,
    SoftPreference,
)
from mandatelab_engine import (
    AUTHORIZATION_DEFAULTED_FROM_POLICY,
    AUTHORIZATION_MISSING_SAFE_ZERO_APPLIED,
    CATEGORY_INFERRED_FROM_PROFILE,
    GOAL_INFERRED_FROM_RAW_TEXT,
    PROFILE_RULE_REQUIRES_CONFIRMATION,
    MandateConversionError,
    parse_mandate,
)


PROFILE_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "examples"
    / "buyer_preference_profile.json"
)
NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)


def profile(*, confirmed_rule: bool = False) -> BuyerPreferenceProfile:
    payload = json.loads(PROFILE_EXAMPLE.read_text(encoding="utf-8"))
    if confirmed_rule:
        payload["hard_rule_candidates"][0]["requires_confirmation"] = False
    return BuyerPreferenceProfile.model_validate(payload)


def authorization(
    autonomous: str = "200", maximum: str = "250"
) -> AuthorizationPolicy:
    return AuthorizationPolicy(
        autonomous_spend_limit=Money(amount=autonomous),
        maximum_authorized_total=Money(amount=maximum),
    )


def intent(**updates: object) -> PurchaseIntent:
    payload: dict[str, object] = {
        "intent_id": "intent-headphones-1",
        "buyer_id": "buyer-maya",
        "raw_text": "Buy noise-cancelling headphones under $250.",
        "goal": "Buy noise-cancelling headphones",
        "category": "headphones",
        "authorization": authorization(),
        "created_at": NOW,
    }
    payload.update(updates)
    return PurchaseIntent.model_validate(payload)


def test_explicit_intent_fields_are_preserved_in_mandate() -> None:
    max_price = HardConstraint(
        constraint_id="max-price",
        kind=ConstraintKind.MAX_LANDED_PRICE,
        operator=ConstraintOperator.LTE,
        expected=Money(amount="250"),
        source=MandateSource.CURRENT_EXPLICIT,
    )
    brand = SoftPreference(
        preference_id="prefer-sony",
        attribute=PreferenceAttribute.BRAND,
        direction=PreferenceDirection.PREFER,
        preferred_value="Sony",
        weight="0.8",
        source=PreferenceSource.CURRENT_EXPLICIT,
        confidence="1",
    )
    purchase_intent = intent(
        hard_constraints=[max_price],
        soft_preferences=[brand],
        material_ambiguities=["COLOR_NOT_SPECIFIED"],
    )

    mandate = parse_mandate(purchase_intent, profile(), mandate_id="mandate-1")

    assert mandate.mandate_id == "mandate-1"
    assert mandate.goal == purchase_intent.goal
    assert mandate.category == purchase_intent.category
    assert mandate.hard_constraints == [max_price]
    assert mandate.soft_preferences == [brand]
    assert mandate.authorization == purchase_intent.authorization
    assert mandate.material_ambiguities == [
        "COLOR_NOT_SPECIFIED",
        f"{PROFILE_RULE_REQUIRES_CONFIRMATION}:rule-candidate-new-only",
    ]
    assert mandate.created_at == purchase_intent.created_at


def test_confirmed_profile_rule_becomes_a_mandate_constraint() -> None:
    mandate = parse_mandate(intent(), profile(confirmed_rule=True))

    assert len(mandate.hard_constraints) == 1
    rule = mandate.hard_constraints[0]
    assert rule.constraint_id == "profile:rule-candidate-new-only"
    assert rule.source is MandateSource.CONFIRMED_PROFILE_RULE
    assert rule.confidence == Decimal("1.0")
    assert rule.expected == ["NEW"]


def test_current_constraint_overrides_profile_rule_of_the_same_kind() -> None:
    current_rule = HardConstraint(
        constraint_id="allow-refurbished",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW", "REFURBISHED"],
        source=MandateSource.CURRENT_EXPLICIT,
    )

    mandate = parse_mandate(
        intent(hard_constraints=[current_rule]), profile(confirmed_rule=True)
    )

    assert mandate.hard_constraints == [current_rule]


def test_unconfirmed_profile_rule_is_an_ambiguity_not_a_constraint() -> None:
    mandate = parse_mandate(intent(), profile())

    assert mandate.hard_constraints == []
    assert mandate.material_ambiguities == [
        f"{PROFILE_RULE_REQUIRES_CONFIRMATION}:rule-candidate-new-only"
    ]


def test_explicit_different_category_excludes_category_profile_rules() -> None:
    mandate = parse_mandate(
        intent(category="speakers"), profile(confirmed_rule=True)
    )

    assert mandate.category == "speakers"
    assert mandate.hard_constraints == []
    assert mandate.material_ambiguities == []


def test_missing_fields_use_safe_fallbacks_and_material_ambiguities() -> None:
    purchase_intent = intent(goal=None, category=None, authorization=None)

    mandate = parse_mandate(purchase_intent, profile())

    assert mandate.goal == purchase_intent.raw_text
    assert mandate.category == "headphones"
    assert mandate.authorization.autonomous_spend_limit.amount == Decimal("0")
    assert mandate.authorization.maximum_authorized_total.amount == Decimal("0")
    assert mandate.authorization.substitution_allowed is False
    assert GOAL_INFERRED_FROM_RAW_TEXT in mandate.material_ambiguities
    assert CATEGORY_INFERRED_FROM_PROFILE in mandate.material_ambiguities
    assert AUTHORIZATION_MISSING_SAFE_ZERO_APPLIED in mandate.material_ambiguities


def test_configured_authorization_default_is_used_and_disclosed() -> None:
    default = authorization(autonomous="150", maximum="300")

    mandate = parse_mandate(
        intent(authorization=None), profile(), default_authorization=default
    )

    assert mandate.authorization == default
    assert AUTHORIZATION_DEFAULTED_FROM_POLICY in mandate.material_ambiguities
    assert AUTHORIZATION_MISSING_SAFE_ZERO_APPLIED not in mandate.material_ambiguities


def test_duplicate_ambiguities_are_removed_without_reordering() -> None:
    purchase_intent = intent(
        goal=None,
        material_ambiguities=[GOAL_INFERRED_FROM_RAW_TEXT, "COLOR_NOT_SPECIFIED"],
    )

    mandate = parse_mandate(purchase_intent, profile())

    assert mandate.material_ambiguities.count(GOAL_INFERRED_FROM_RAW_TEXT) == 1
    assert mandate.material_ambiguities[:2] == [
        GOAL_INFERRED_FROM_RAW_TEXT,
        "COLOR_NOT_SPECIFIED",
    ]


def test_mismatched_buyer_ids_are_rejected() -> None:
    other_profile = profile().model_copy(update={"buyer_id": "buyer-other"})

    with pytest.raises(MandateConversionError, match="buyer_id must match"):
        parse_mandate(intent(), other_profile)


def test_generated_mandate_round_trips_through_shared_json_contract() -> None:
    mandate = parse_mandate(intent(), profile(confirmed_rule=True))

    assert mandate.mandate_id == "mandate:intent-headphones-1"
    assert Mandate.model_validate_json(mandate.model_dump_json()) == mandate


def test_profile_importance_signals_remain_separate_from_current_preferences() -> None:
    learned_signal = PreferenceSignal[ImportanceLevel](
        value=ImportanceLevel.HIGH,
        numeric_weight="0.9",
        source=PreferenceSource.CATEGORY_HISTORY,
        confidence="0.8",
    )
    learned_profile = profile().model_copy(
        update={"quality_importance": learned_signal}
    )

    mandate = parse_mandate(intent(), learned_profile)

    assert mandate.soft_preferences == []
