"""Conformance: history-derived profiles satisfy the shared contract."""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("pydantic", reason="shared contracts require Pydantic")

from buyer_history import build_profile_from_workbook  # noqa: E402
from buyer_history.contract import (  # noqa: E402
    GENERAL_CATEGORY,
    PurchaseHistoryProfileBuilder,
    all_contract_profiles,
    to_contract_profile,
)
from mandatelab_contracts import (  # noqa: E402
    BuyerPreferenceProfile,
    ImportanceLevel,
    PreferenceSource,
)

WORKBOOK = "buyer_history/fixtures/synthetic_household.xlsx"
TODAY = date(2026, 8, 16)


@pytest.fixture(scope="module")
def bundle():
    return build_profile_from_workbook(WORKBOOK, buyer_id="synthetic_household", as_of=TODAY)


def test_builder_satisfies_the_shared_protocol(bundle) -> None:
    profile = PurchaseHistoryProfileBuilder("Groceries > Coffee").build_profile(bundle)
    assert isinstance(profile, BuyerPreferenceProfile)
    assert profile.category == "Groceries > Coffee"
    assert profile.buyer_id == "synthetic_household"


def test_profile_round_trips_through_json(bundle) -> None:
    profile = to_contract_profile(bundle, "Groceries > Coffee")
    restored = BuyerPreferenceProfile.model_validate_json(profile.model_dump_json())
    assert restored == profile


def test_unobservable_attributes_stay_unknown(bundle) -> None:
    """The whole point: never assert a level the data cannot support."""
    profile = to_contract_profile(bundle, "Groceries > Coffee")
    for field in ("delivery_importance", "return_policy_importance", "merchant_trust_importance"):
        signal = getattr(profile, field)
        assert signal.value is ImportanceLevel.UNKNOWN, field
        assert signal.confidence == 0, field
        assert signal.source is PreferenceSource.DEFAULT, field
    assert profile.condition_preferences == []


def test_observed_attributes_carry_real_scores(bundle) -> None:
    profile = to_contract_profile(bundle, "Groceries > Coffee")
    assert profile.price_sensitivity.value is ImportanceLevel.HIGH
    assert 0 < profile.price_sensitivity.numeric_weight <= 1
    assert profile.price_sensitivity.source is PreferenceSource.CATEGORY_HISTORY


def test_scope_is_carried_by_source(bundle) -> None:
    """Category vs buyer-wide is distinguished by PreferenceSource, not shape."""
    general = to_contract_profile(bundle, None)
    assert general.category == GENERAL_CATEGORY
    assert general.price_sensitivity.source is PreferenceSource.GENERAL_HISTORY


def test_behaviour_never_proposes_hard_rules(bundle) -> None:
    """Only the cold-start path may propose candidate hard rules."""
    for profile in all_contract_profiles(bundle).values():
        assert profile.hard_rule_candidates == []


def test_every_category_emits_a_valid_profile(bundle) -> None:
    profiles = all_contract_profiles(bundle)
    assert len(profiles) == len(bundle.categories) + 1
    assert all(isinstance(p, BuyerPreferenceProfile) for p in profiles.values())
