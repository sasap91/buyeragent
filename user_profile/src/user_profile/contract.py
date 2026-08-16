"""Adapter from Luke's cold-start model into the shared profile contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import sqrt
from typing import Protocol

from mandatelab_contracts import (
    BuyerPreferenceProfile,
    ImportanceLevel,
    PreferenceSignal,
    PreferenceSource,
)

from user_profile.product import Product


class ProbabilityModel(Protocol):
    def buy_probability(self, product: Product) -> float: ...


@dataclass(frozen=True, slots=True)
class ColdStartProfileInput:
    buyer_id: str
    category: str
    price_sensitivity: float | None
    quality_importance: float | None
    brand_scores: dict[str, float]
    confidence: float
    created_at: datetime


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(_clamp(value), 4)))


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or len(left) != len(right):
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right, strict=True)
    )
    left_scale = sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        return 0.0
    return numerator / (left_scale * right_scale)


def profile_input_from_model(
    model: ProbabilityModel,
    catalog: Sequence[Product],
    *,
    buyer_id: str,
    category: str,
    observation_count: int,
    created_at: datetime,
) -> ColdStartProfileInput:
    """Summarize model behavior without depending on its private coefficients."""

    scoped = [
        product
        for product in catalog
        if category == "*" or product.category.casefold() == category.casefold()
    ]
    confidence = _clamp(observation_count / 5)
    if not scoped or observation_count == 0:
        return ColdStartProfileInput(
            buyer_id=buyer_id,
            category=category,
            price_sensitivity=None,
            quality_importance=None,
            brand_scores={},
            confidence=0.0,
            created_at=created_at,
        )

    probabilities = [_clamp(model.buy_probability(item)) for item in scoped]
    price_correlation = _pearson(
        [item.price for item in scoped], probabilities
    )
    quality_correlation = _pearson(
        [item.quality for item in scoped], probabilities
    )
    brand_values: dict[str, list[float]] = {}
    for product, probability in zip(scoped, probabilities, strict=True):
        brand_values.setdefault(product.brand, []).append(probability)
    brand_scores = {
        brand: sum(values) / len(values)
        for brand, values in brand_values.items()
    }
    return ColdStartProfileInput(
        buyer_id=buyer_id,
        category=category,
        price_sensitivity=max(0.0, -price_correlation),
        quality_importance=max(0.0, quality_correlation),
        brand_scores=brand_scores,
        confidence=confidence,
        created_at=created_at,
    )


def _importance(
    value: float | None, confidence: float
) -> PreferenceSignal[ImportanceLevel]:
    if value is None:
        return PreferenceSignal[ImportanceLevel](
            value=ImportanceLevel.UNKNOWN,
            numeric_weight=Decimal("0"),
            source=PreferenceSource.DEFAULT,
            confidence=Decimal("0"),
        )
    weight = _clamp(value)
    if weight < 0.34:
        level = ImportanceLevel.LOW
    elif weight < 0.67:
        level = ImportanceLevel.MEDIUM
    else:
        level = ImportanceLevel.HIGH
    return PreferenceSignal[ImportanceLevel](
        value=level,
        numeric_weight=_decimal(weight),
        source=PreferenceSource.COLD_START,
        confidence=_decimal(confidence),
    )


class ColdStartProfileBuilder:
    """Structurally implements PreferenceProfileBuilder[ColdStartProfileInput]."""

    def build_profile(
        self, source: ColdStartProfileInput, /
    ) -> BuyerPreferenceProfile:
        confidence = _clamp(source.confidence)
        preferred = []
        disliked = []
        for brand, raw_score in sorted(source.brand_scores.items()):
            score = _clamp(raw_score)
            distance = abs(score - 0.5) * 2
            if distance == 0:
                continue
            signal = PreferenceSignal[str](
                value=brand,
                numeric_weight=_decimal(distance),
                source=PreferenceSource.COLD_START,
                confidence=_decimal(confidence),
            )
            if score >= 0.60:
                preferred.append(signal)
            elif score <= 0.40:
                disliked.append(signal)

        unknown = _importance(None, 0.0)
        return BuyerPreferenceProfile(
            buyer_id=source.buyer_id,
            category=source.category,
            price_sensitivity=_importance(
                source.price_sensitivity, confidence
            ),
            quality_importance=_importance(
                source.quality_importance, confidence
            ),
            delivery_importance=unknown,
            return_policy_importance=unknown,
            merchant_trust_importance=unknown,
            preferred_brands=preferred,
            disliked_brands=disliked,
            condition_preferences=[],
            hard_rule_candidates=[],
            created_at=source.created_at,
        )
