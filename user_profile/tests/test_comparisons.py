"""Each curated pair's LEFT/RIGHT maps onto the intended preference axis."""

from __future__ import annotations

from user_profile.comparisons import (
    ComparisonChoice,
    ComparisonResponse,
    load_comparison_catalog,
)
from user_profile.contract import ColdStartProfileBuilder
from mandatelab_contracts import ImportanceLevel, ProductCondition


def _profile(pair_id: str, choice: str):
    builder = ColdStartProfileBuilder()
    return builder.build_profile(
        [ComparisonResponse(pair_id=pair_id, choice=ComparisonChoice(choice))]
    )


def test_catalog_has_demo_and_stretch_pairs() -> None:
    catalog = load_comparison_catalog()
    assert catalog.demo_pair_count == 5
    assert len(catalog.pairs) == 8
    assert {pair.pair_id for pair in catalog.demo_pairs()} == {
        "price-vs-quality",
        "brand-vs-price",
        "delivery-vs-price",
        "new-vs-refurbished",
        "returns-vs-price",
    }
    for pair in catalog.pairs:
        assert pair.left.condition
        assert pair.left.delivery_days is not None
        assert pair.left.return_window_days is not None
        assert pair.right.condition
        assert pair.right.delivery_days is not None
        assert pair.right.return_window_days is not None


def test_price_vs_quality_left_prefers_price() -> None:
    profile = _profile("price-vs-quality", "LEFT")
    assert profile.price_sensitivity.value is ImportanceLevel.HIGH
    assert profile.quality_importance.value is ImportanceLevel.LOW


def test_price_vs_quality_right_prefers_quality() -> None:
    profile = _profile("price-vs-quality", "RIGHT")
    assert profile.price_sensitivity.value is ImportanceLevel.LOW
    assert profile.quality_importance.value is ImportanceLevel.HIGH


def test_brand_vs_price_left_prefers_sony() -> None:
    profile = _profile("brand-vs-price", "LEFT")
    assert [signal.value for signal in profile.preferred_brands] == ["Sony"]
    assert profile.price_sensitivity.value is ImportanceLevel.LOW


def test_delivery_vs_price_left_values_speed() -> None:
    profile = _profile("delivery-vs-price", "LEFT")
    assert profile.delivery_importance.value is ImportanceLevel.HIGH
    assert profile.price_sensitivity.value is ImportanceLevel.LOW


def test_delivery_vs_price_right_values_savings() -> None:
    profile = _profile("delivery-vs-price", "RIGHT")
    assert profile.delivery_importance.value is ImportanceLevel.LOW
    assert profile.price_sensitivity.value is ImportanceLevel.HIGH


def test_new_vs_refurbished_left_prohibits_refurbished() -> None:
    profile = _profile("new-vs-refurbished", "LEFT")
    assert profile.hard_rule_candidates
    assert profile.condition_preferences[0].value is ProductCondition.NEW


def test_new_vs_refurbished_right_allows_refurbished() -> None:
    profile = _profile("new-vs-refurbished", "RIGHT")
    assert profile.hard_rule_candidates == []
    assert ProductCondition.REFURBISHED in [
        signal.value for signal in profile.condition_preferences
    ]


def test_new_vs_refurbished_neither_is_a_prohibition() -> None:
    profile = _profile("new-vs-refurbished", "NEITHER")
    assert profile.hard_rule_candidates
    assert profile.hard_rule_candidates[0].expected == ["NEW"]


def test_returns_vs_price_left_values_returns() -> None:
    profile = _profile("returns-vs-price", "LEFT")
    assert profile.return_policy_importance.value is ImportanceLevel.HIGH
    assert profile.price_sensitivity.value is ImportanceLevel.LOW


def test_unanswered_axes_stay_unknown() -> None:
    profile = _profile("price-vs-quality", "RIGHT")
    assert profile.delivery_importance.value is ImportanceLevel.UNKNOWN
    assert profile.return_policy_importance.value is ImportanceLevel.UNKNOWN
    assert profile.merchant_trust_importance.value is ImportanceLevel.UNKNOWN
