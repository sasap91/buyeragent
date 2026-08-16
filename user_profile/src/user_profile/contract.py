"""Adapter onto the shared `mandatelab_contracts.BuyerPreferenceProfile`.

`ColdStartProfileBuilder` implements the `PreferenceProfileBuilder` protocol so a
comparison-derived profile is interchangeable with a history-derived one
everywhere downstream.

Importance levels come from which side of each curated trade-off won — not from
the Bayesian weights, which stay a live visualization only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from user_profile.comparisons import (
    AXES_FOR_TRADEOFF,
    TRUSTED_MERCHANTS,
    ComparisonCatalog,
    ComparisonChoice,
    ComparisonPair,
    ComparisonResponse,
    load_comparison_catalog,
)

_FALLBACK_WEIGHT = {
    "HIGH": Decimal("0.85"),
    "MEDIUM": Decimal("0.55"),
    "LOW": Decimal("0.25"),
    "UNKNOWN": Decimal("0"),
}
_EPS = 1e-6


def _unit(value: float) -> Decimal:
    return Decimal(str(round(min(1.0, max(0.0, value)), 4)))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _bucket(votes: list[float]) -> tuple[str, Decimal, Decimal]:
    if not votes:
        return "UNKNOWN", Decimal("0"), Decimal("0")
    mean = _mean(votes)
    confidence = _unit(0.55 + 0.15 * len(votes))
    if mean > 0.4:
        level = "HIGH"
    elif mean < -0.4:
        level = "LOW"
    else:
        level = "MEDIUM"
    return level, _FALLBACK_WEIGHT[level], confidence


def _importance_signal(votes: list[float], *, learned: bool):
    from mandatelab_contracts import ImportanceLevel, PreferenceSignal, PreferenceSource

    level, weight, confidence = _bucket(votes)
    if level == "UNKNOWN":
        return PreferenceSignal[ImportanceLevel](
            value=ImportanceLevel.UNKNOWN,
            numeric_weight=Decimal("0"),
            source=PreferenceSource.DEFAULT,
            confidence=Decimal("0"),
        )
    return PreferenceSignal[ImportanceLevel](
        value=ImportanceLevel(level),
        numeric_weight=weight,
        source=PreferenceSource.COLD_START if learned else PreferenceSource.DEFAULT,
        confidence=confidence,
    )


def _brand_signals(scores: dict[str, float]):
    from mandatelab_contracts import PreferenceSignal, PreferenceSource

    positive = {brand: score for brand, score in scores.items() if score > 0}
    if not positive:
        return []
    peak = max(positive.values())
    ranked = sorted(positive.items(), key=lambda item: (-item[1], item[0]))
    return [
        PreferenceSignal[str](
            value=brand,
            numeric_weight=_unit(score / peak),
            source=PreferenceSource.COLD_START,
            confidence=_unit(0.6 + 0.2 * min(score, 2.0)),
        )
        for brand, score in ranked
    ]


def _condition_new_only():
    from mandatelab_contracts import (
        ConstraintKind,
        ConstraintOperator,
        HardRuleCandidate,
        PreferenceSignal,
        PreferenceSource,
        ProductCondition,
    )

    signal = PreferenceSignal[ProductCondition](
        value=ProductCondition.NEW,
        numeric_weight=Decimal("1.0"),
        source=PreferenceSource.COLD_START,
        confidence=Decimal("1.0"),
    )
    rule = HardRuleCandidate(
        candidate_id="rule-candidate-new-only",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW"],
        source=PreferenceSource.COLD_START,
        confidence=Decimal("1.0"),
        requires_confirmation=True,
        rationale="Buyer selected new only during cold-start comparisons.",
    )
    return [signal], [rule]


def _condition_refurbished_allowed():
    from mandatelab_contracts import PreferenceSignal, PreferenceSource, ProductCondition

    return [
        PreferenceSignal[ProductCondition](
            value=ProductCondition.NEW,
            numeric_weight=Decimal("0.55"),
            source=PreferenceSource.COLD_START,
            confidence=Decimal("0.7"),
        ),
        PreferenceSignal[ProductCondition](
            value=ProductCondition.REFURBISHED,
            numeric_weight=Decimal("0.85"),
            source=PreferenceSource.COLD_START,
            confidence=Decimal("0.85"),
        ),
    ]


def _record_attribute_votes(
    chosen: object,
    other: object,
    axes: frozenset[str],
    votes: dict[str, list[float]],
    brand_scores: dict[str, float],
) -> None:
    if "price" in axes:
        delta = chosen.price - other.price  # type: ignore[attr-defined]
        if abs(delta) > _EPS:
            votes["price"].append(1.0 if delta < 0 else -1.0)
    if "quality" in axes:
        delta = chosen.quality - other.quality  # type: ignore[attr-defined]
        if abs(delta) > _EPS:
            votes["quality"].append(1.0 if delta > 0 else -1.0)
    if "delivery" in axes:
        chosen_days = chosen.delivery_days  # type: ignore[attr-defined]
        other_days = other.delivery_days  # type: ignore[attr-defined]
        if chosen_days is not None and other_days is not None and chosen_days != other_days:
            votes["delivery"].append(1.0 if chosen_days < other_days else -1.0)
    if "returns" in axes:
        chosen_days = chosen.return_window_days  # type: ignore[attr-defined]
        other_days = other.return_window_days  # type: ignore[attr-defined]
        if chosen_days is not None and other_days is not None and chosen_days != other_days:
            votes["returns"].append(1.0 if chosen_days > other_days else -1.0)
    if "brand" in axes:
        chosen_brand = chosen.brand  # type: ignore[attr-defined]
        other_brand = other.brand  # type: ignore[attr-defined]
        if chosen_brand and other_brand and chosen_brand.casefold() != other_brand.casefold():
            brand_scores[chosen_brand] += 1.0
    if "merchant" in axes:
        chosen_merchant = chosen.merchant  # type: ignore[attr-defined]
        other_merchant = other.merchant  # type: ignore[attr-defined]
        if chosen_merchant and other_merchant and chosen_merchant != other_merchant:
            chosen_trusted = chosen_merchant in TRUSTED_MERCHANTS
            other_trusted = other_merchant in TRUSTED_MERCHANTS
            if chosen_trusted != other_trusted:
                votes["merchant"].append(1.0 if chosen_trusted else -1.0)


def _either_votes(
    pair: ComparisonPair,
    axes: frozenset[str],
    votes: dict[str, list[float]],
    brand_scores: dict[str, float],
) -> None:
    for axis in ("price", "quality", "delivery", "returns", "merchant"):
        if axis in axes:
            votes[axis].append(0.0)
    if "brand" in axes:
        for brand in (pair.left.brand, pair.right.brand):
            if brand:
                brand_scores[brand] += 0.5


def to_contract_profile(
    responses: Sequence[ComparisonResponse],
    *,
    buyer_id: str,
    category: str,
    catalog: ComparisonCatalog,
    created_at: datetime | None = None,
):
    """Emit the shared BuyerPreferenceProfile from pairwise comparison answers."""
    from mandatelab_contracts import BuyerPreferenceProfile

    pairs = catalog.pair_map()
    votes: dict[str, list[float]] = defaultdict(list)
    brand_scores: dict[str, float] = defaultdict(float)
    new_only = False
    refurbished_ok = False

    for response in responses:
        pair = pairs.get(response.pair_id)
        if pair is None:
            raise KeyError(f"unknown comparison pair: {response.pair_id}")
        axes = AXES_FOR_TRADEOFF.get(pair.tradeoff, frozenset())

        if response.choice is ComparisonChoice.EITHER:
            _either_votes(pair, axes, votes, brand_scores)
            if pair.tradeoff == "new_vs_refurbished":
                refurbished_ok = True
            continue

        if response.choice is ComparisonChoice.NEITHER:
            if pair.tradeoff == "new_vs_refurbished":
                new_only = True
            continue

        chosen = pair.left if response.choice is ComparisonChoice.LEFT else pair.right
        other = pair.right if response.choice is ComparisonChoice.LEFT else pair.left
        _record_attribute_votes(chosen, other, axes, votes, brand_scores)

        if pair.tradeoff == "new_vs_refurbished":
            if chosen.condition == "NEW" and other.condition == "REFURBISHED":
                new_only = True
            elif chosen.condition == "REFURBISHED":
                refurbished_ok = True

    if new_only and not refurbished_ok:
        condition_preferences, hard_rules = _condition_new_only()
    elif refurbished_ok:
        condition_preferences, hard_rules = _condition_refurbished_allowed(), []
    else:
        condition_preferences, hard_rules = [], []

    return BuyerPreferenceProfile(
        buyer_id=buyer_id,
        category=category,
        price_sensitivity=_importance_signal(votes["price"], learned=bool(votes["price"])),
        quality_importance=_importance_signal(votes["quality"], learned=bool(votes["quality"])),
        delivery_importance=_importance_signal(
            votes["delivery"], learned=bool(votes["delivery"])
        ),
        return_policy_importance=_importance_signal(
            votes["returns"], learned=bool(votes["returns"])
        ),
        merchant_trust_importance=_importance_signal(
            votes["merchant"], learned=bool(votes["merchant"])
        ),
        preferred_brands=_brand_signals(brand_scores),
        disliked_brands=[],
        condition_preferences=condition_preferences,
        hard_rule_candidates=hard_rules,
        created_at=created_at or datetime.now(UTC),
    )


class ColdStartProfileBuilder:
    """`PreferenceProfileBuilder` bound to pairwise-comparison input (PRD 5.1).

        builder = ColdStartProfileBuilder(buyer_id="buyer-maya")
        profile = builder.build_profile(responses)
    """

    def __init__(
        self,
        buyer_id: str = "buyer-maya",
        category: str | None = None,
        catalog: ComparisonCatalog | None = None,
    ) -> None:
        self.catalog = catalog or load_comparison_catalog()
        self.buyer_id = buyer_id
        self.category = category or self.catalog.category

    def build_profile(
        self, source: Sequence[ComparisonResponse], /
    ):
        from mandatelab_contracts import BuyerPreferenceProfile

        profile = to_contract_profile(
            source,
            buyer_id=self.buyer_id,
            category=self.category,
            catalog=self.catalog,
        )
        assert isinstance(profile, BuyerPreferenceProfile)
        return profile
