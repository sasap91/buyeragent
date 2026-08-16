"""Conformance: cold-start profiles satisfy the shared contract."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

pytest.importorskip("pydantic", reason="shared contracts require Pydantic")

from mandatelab_contracts import (  # noqa: E402
    BuyerPreferenceProfile,
    ConstraintKind,
    ImportanceLevel,
    PreferenceProfileBuilder,
    PreferenceSource,
    ProductCondition,
)
from user_profile.comparisons import (  # noqa: E402
    ComparisonResponse,
    load_maya_comparisons,
)
from user_profile.contract import ColdStartProfileBuilder  # noqa: E402


def consume_profile_builder(
    builder: PreferenceProfileBuilder[Sequence[ComparisonResponse]],
    source: Sequence[ComparisonResponse],
) -> BuyerPreferenceProfile:
    return builder.build_profile(source)


def test_builder_satisfies_the_shared_protocol() -> None:
    buyer_id, category, responses = load_maya_comparisons()
    profile = consume_profile_builder(
        ColdStartProfileBuilder(buyer_id=buyer_id, category=category),
        responses,
    )
    assert isinstance(profile, BuyerPreferenceProfile)
    assert profile.buyer_id == "buyer-maya"
    assert profile.category == "headphones"


def test_empty_comparisons_leave_unobservable_axes_unknown() -> None:
    profile = ColdStartProfileBuilder().build_profile([])
    for field in (
        "price_sensitivity",
        "quality_importance",
        "delivery_importance",
        "return_policy_importance",
        "merchant_trust_importance",
    ):
        signal = getattr(profile, field)
        assert signal.value is ImportanceLevel.UNKNOWN, field
        assert signal.confidence == 0, field
        assert signal.source is PreferenceSource.DEFAULT, field
    assert profile.preferred_brands == []
    assert profile.hard_rule_candidates == []


def test_profile_round_trips_through_json() -> None:
    _, _, responses = load_maya_comparisons()
    profile = ColdStartProfileBuilder().build_profile(responses)
    restored = BuyerPreferenceProfile.model_validate_json(profile.model_dump_json())
    assert restored == profile


def test_learned_signals_are_cold_start() -> None:
    _, _, responses = load_maya_comparisons()
    profile = ColdStartProfileBuilder().build_profile(responses)
    assert profile.quality_importance.source is PreferenceSource.COLD_START
    assert profile.price_sensitivity.source is PreferenceSource.COLD_START
    assert profile.preferred_brands[0].source is PreferenceSource.COLD_START


def test_maya_fixture_matches_demo_preferences() -> None:
    buyer_id, category, responses = load_maya_comparisons()
    profile = ColdStartProfileBuilder(buyer_id=buyer_id, category=category).build_profile(
        responses
    )
    assert profile.quality_importance.value is ImportanceLevel.HIGH
    assert profile.delivery_importance.value is ImportanceLevel.LOW
    assert profile.return_policy_importance.value is ImportanceLevel.HIGH
    assert profile.preferred_brands[0].value == "Sony"
    assert profile.condition_preferences[0].value is ProductCondition.NEW
    assert profile.hard_rule_candidates[0].kind is ConstraintKind.ALLOWED_CONDITION
    assert profile.hard_rule_candidates[0].requires_confirmation is True
    assert profile.hard_rule_candidates[0].expected == ["NEW"]


def test_refurbished_prohibition_emits_a_hard_rule_candidate() -> None:
    _, _, responses = load_maya_comparisons()
    profile = ColdStartProfileBuilder().build_profile(responses)
    assert any(
        candidate.kind is ConstraintKind.ALLOWED_CONDITION
        and candidate.expected == ["NEW"]
        for candidate in profile.hard_rule_candidates
    )
