from __future__ import annotations

from datetime import datetime, timezone

from mandatelab_contracts import (
    BuyerPreferenceProfile,
    ImportanceLevel,
    PreferenceProfileBuilder,
    PreferenceSource,
)
from user_profile.contract import (
    ColdStartProfileBuilder,
    ColdStartProfileInput,
    profile_input_from_model,
)
from user_profile.product import Product


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)


class FakeModel:
    probabilities = {
        "sony": 0.90,
        "bose": 0.75,
        "generic": 0.15,
    }

    def buy_probability(self, product: Product) -> float:
        return self.probabilities[product.id]


def catalog() -> list[Product]:
    return [
        Product("sony", "Sony", "headphones", "Sony", 100, 0.95, 0.5),
        Product("bose", "Bose", "headphones", "Bose", 150, 0.80, 0.4),
        Product(
            "generic",
            "Generic",
            "headphones",
            "Generic",
            300,
            0.25,
            0.2,
        ),
    ]


def test_builder_satisfies_shared_profile_protocol() -> None:
    builder: PreferenceProfileBuilder[ColdStartProfileInput] = (
        ColdStartProfileBuilder()
    )
    evidence = profile_input_from_model(
        FakeModel(),
        catalog(),
        buyer_id="buyer-cold-start",
        category="headphones",
        observation_count=5,
        created_at=NOW,
    )

    profile = builder.build_profile(evidence)

    assert isinstance(profile, BuyerPreferenceProfile)
    assert profile.buyer_id == "buyer-cold-start"
    assert profile.category == "headphones"
    assert profile.price_sensitivity.value is ImportanceLevel.HIGH
    assert profile.quality_importance.value is ImportanceLevel.HIGH
    assert profile.price_sensitivity.source is PreferenceSource.COLD_START
    assert {signal.value for signal in profile.preferred_brands} == {
        "Bose",
        "Sony",
    }
    assert [signal.value for signal in profile.disliked_brands] == [
        "Generic"
    ]


def test_unobservable_fields_are_explicitly_unknown() -> None:
    profile = ColdStartProfileBuilder().build_profile(
        ColdStartProfileInput(
            buyer_id="buyer-cold-start",
            category="headphones",
            price_sensitivity=0.5,
            quality_importance=0.8,
            brand_scores={},
            confidence=0.75,
            created_at=NOW,
        )
    )

    for field in (
        "delivery_importance",
        "return_policy_importance",
        "merchant_trust_importance",
    ):
        signal = getattr(profile, field)
        assert signal.value is ImportanceLevel.UNKNOWN
        assert signal.confidence == 0
        assert signal.source is PreferenceSource.DEFAULT
    assert profile.condition_preferences == []
    assert profile.hard_rule_candidates == []


def test_no_contrast_produces_an_unknown_profile_not_guessed_preferences() -> None:
    evidence = profile_input_from_model(
        FakeModel(),
        catalog(),
        buyer_id="buyer-cold-start",
        category="headphones",
        observation_count=0,
        created_at=NOW,
    )

    profile = ColdStartProfileBuilder().build_profile(evidence)

    assert profile.price_sensitivity.value is ImportanceLevel.UNKNOWN
    assert profile.quality_importance.value is ImportanceLevel.UNKNOWN
    assert profile.preferred_brands == []
    assert profile.disliked_brands == []
