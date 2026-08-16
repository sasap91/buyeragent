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
    Mandate,
    MandateSource,
    Money,
    PreferenceAttribute,
    PreferenceDirection,
    PreferenceSource,
    ProductCondition,
    RankingExplanation,
    SoftPreference,
    TransactionCandidate,
)
from mandatelab_engine import RankingError, rank_candidates


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
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


def load_profile(path: Path) -> BuyerPreferenceProfile:
    return BuyerPreferenceProfile.model_validate_json(path.read_text())


def load_catalog() -> list[TransactionCandidate]:
    payload = json.loads(CATALOG_PATH.read_text())
    return [
        TransactionCandidate.model_validate(candidate)
        for candidate in payload["candidates"]
    ]


def authorization(
    autonomous: str = "200", maximum: str = "600"
) -> AuthorizationPolicy:
    return AuthorizationPolicy(
        autonomous_spend_limit=Money(amount=autonomous),
        maximum_authorized_total=Money(amount=maximum),
    )


def mandate(
    profile: BuyerPreferenceProfile, **updates: object
) -> Mandate:
    payload: dict[str, object] = {
        "mandate_id": "mandate-ranking-1",
        "version": 1,
        "buyer_id": profile.buyer_id,
        "goal": "Buy noise-cancelling headphones",
        "category": "headphones",
        "authorization": authorization(),
        "created_at": NOW,
    }
    payload.update(updates)
    return Mandate.model_validate(payload)


def neutral_profile(
    *, buyer_id: str = "buyer-neutral", category: str = "headphones"
) -> BuyerPreferenceProfile:
    payload = load_profile(MAYA_PROFILE_PATH).model_dump(mode="json")
    payload.update(
        buyer_id=buyer_id,
        category=category,
        preferred_brands=[],
        disliked_brands=[],
        condition_preferences=[],
        hard_rule_candidates=[],
    )
    for field in (
        "price_sensitivity",
        "quality_importance",
        "delivery_importance",
        "return_policy_importance",
        "merchant_trust_importance",
    ):
        payload[field] = {
            "value": "UNKNOWN",
            "numeric_weight": "0",
            "source": "DEFAULT",
            "confidence": "0",
        }
    return BuyerPreferenceProfile.model_validate(payload)


def new_only_rule() -> HardConstraint:
    return HardConstraint(
        constraint_id="new-only",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW"],
        source=MandateSource.CURRENT_EXPLICIT,
    )


def explicit_preference(
    *,
    preference_id: str,
    attribute: PreferenceAttribute,
    direction: PreferenceDirection,
    preferred_value: object,
) -> SoftPreference:
    return SoftPreference(
        preference_id=preference_id,
        attribute=attribute,
        direction=direction,
        preferred_value=preferred_value,
        weight=Decimal("1"),
        source=PreferenceSource.CURRENT_EXPLICIT,
        confidence=Decimal("1"),
    )


def test_same_catalog_produces_buyer_specific_ordering() -> None:
    candidates = load_catalog()
    maya = load_profile(MAYA_PROFILE_PATH)
    theo = load_profile(THEO_PROFILE_PATH)

    maya_ranking = rank_candidates(candidates, mandate(maya), maya)
    theo_ranking = rank_candidates(candidates, mandate(theo), theo)

    assert maya_ranking[0].candidate.candidate_id != (
        theo_ranking[0].candidate.candidate_id
    )
    assert theo_ranking[0].candidate.candidate_id == (
        "catalog-anker-q45-black"
    )


def test_ineligible_candidates_are_removed_before_scoring() -> None:
    profile = load_profile(MAYA_PROFILE_PATH)
    ranking = rank_candidates(
        load_catalog(),
        mandate(
            profile,
            authorization=authorization(autonomous="100", maximum="250"),
            hard_constraints=[new_only_rule()],
        ),
        profile,
    )

    ranked_ids = {item.candidate.candidate_id for item in ranking}
    assert len(ranking) == 7
    assert "catalog-sony-xm5-black" in ranked_ids
    assert "catalog-sony-xm4-silver" not in ranked_ids
    assert "catalog-sony-ult-wear-gray" not in ranked_ids
    assert "catalog-mystery-anc-black" not in ranked_ids
    assert "catalog-bose-qc-ultra-black" not in ranked_ids
    assert all(
        item.candidate.condition is ProductCondition.NEW for item in ranking
    )
    assert all(
        item.candidate.final_landed_price is not None
        and item.candidate.final_landed_price.amount <= Decimal("250")
        for item in ranking
    )


def test_candidate_above_autonomous_limit_remains_rankable() -> None:
    profile = load_profile(MAYA_PROFILE_PATH)
    ranking = rank_candidates(
        load_catalog(),
        mandate(
            profile,
            authorization=authorization(autonomous="100", maximum="250"),
        ),
        profile,
    )

    assert "catalog-sony-xm5-black" in {
        item.candidate.candidate_id for item in ranking
    }


def test_current_brand_preference_replaces_learned_brand_signal() -> None:
    profile = load_profile(MAYA_PROFILE_PATH)
    soundcore = explicit_preference(
        preference_id="prefer-soundcore-now",
        attribute=PreferenceAttribute.BRAND,
        direction=PreferenceDirection.PREFER,
        preferred_value="Soundcore",
    )

    ranking = rank_candidates(
        load_catalog(),
        mandate(profile, soft_preferences=[soundcore]),
        profile,
    )

    assert ranking[0].candidate.candidate_id == "catalog-anker-q45-black"
    assert "prefer-soundcore-now" in (
        ranking[0].explanation.influential_preferences
    )
    assert not any(
        influence.startswith("profile:preferred_brand")
        for influence in ranking[0].explanation.influential_preferences
    )


def test_maximize_return_policy_rewards_the_longer_window() -> None:
    profile = neutral_profile()
    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in load_catalog()
    }
    short_returns = candidates_by_id["catalog-apple-airpods-max-blue"]
    long_returns = candidates_by_id["catalog-sony-xm4-silver"]
    preference = explicit_preference(
        preference_id="maximize-returns",
        attribute=PreferenceAttribute.RETURN_POLICY,
        direction=PreferenceDirection.MAXIMIZE,
        preferred_value=True,
    )

    ranking = rank_candidates(
        [short_returns, long_returns],
        mandate(profile, soft_preferences=[preference]),
        profile,
    )

    assert ranking[0].candidate == long_returns
    assert ranking[0].explanation.total_score == Decimal("1.0000")
    assert ranking[1].explanation.total_score == Decimal("0.0000")


def test_unobservable_preference_components_are_omitted() -> None:
    profile = load_profile(MAYA_PROFILE_PATH)
    known = load_catalog()[0]
    unknown = known.model_copy(
        update={
            "candidate_id": "candidate-unknown-logistics",
            "delivery_date": None,
            "return_policy": None,
        }
    )

    ranking = rank_candidates([known, unknown], mandate(profile), profile)
    explanation = next(
        item.explanation
        for item in ranking
        if item.candidate.candidate_id == "candidate-unknown-logistics"
    )

    assert PreferenceAttribute.DELIVERY not in explanation.component_scores
    assert PreferenceAttribute.RETURN_POLICY not in (
        explanation.component_scores
    )


def test_ranking_is_stable_and_explanation_round_trips() -> None:
    profile = neutral_profile()
    candidates = load_catalog()[:3]

    forward = rank_candidates(candidates, mandate(profile), profile)
    reverse = rank_candidates(
        list(reversed(candidates)), mandate(profile), profile
    )

    expected_ids = sorted(candidate.candidate_id for candidate in candidates)
    assert [item.candidate.candidate_id for item in forward] == expected_ids
    assert [item.candidate.candidate_id for item in reverse] == expected_ids
    explanation = forward[0].explanation
    assert explanation.total_score == Decimal("0.5000")
    assert explanation.component_scores == {}
    assert RankingExplanation.model_validate_json(
        explanation.model_dump_json()
    ) == explanation


def test_duplicate_candidate_ids_are_rejected() -> None:
    profile = neutral_profile()
    candidate = load_catalog()[0]

    with pytest.raises(RankingError, match="candidate_id values"):
        rank_candidates([candidate, candidate], mandate(profile), profile)


def test_profile_and_mandate_identity_must_match() -> None:
    profile = neutral_profile()
    candidates = load_catalog()[:1]

    with pytest.raises(RankingError, match="buyer_id"):
        rank_candidates(
            candidates,
            mandate(profile, buyer_id="another-buyer"),
            profile,
        )
    with pytest.raises(RankingError, match="category"):
        rank_candidates(
            candidates,
            mandate(profile, category="laptops"),
            profile,
        )


def test_wildcard_profile_category_is_accepted() -> None:
    profile = neutral_profile(category="*")

    ranking = rank_candidates(
        load_catalog()[:1], mandate(profile, category="laptops"), profile
    )

    assert len(ranking) == 1


def test_no_feasible_candidates_returns_an_empty_ranking() -> None:
    profile = neutral_profile()

    ranking = rank_candidates(
        load_catalog(),
        mandate(
            profile,
            authorization=authorization(autonomous="0", maximum="0"),
        ),
        profile,
    )

    assert ranking == []
