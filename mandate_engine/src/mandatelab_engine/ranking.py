from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from mandatelab_contracts import (
    BuyerPreferenceProfile,
    ConstraintStatus,
    ImportanceLevel,
    Mandate,
    Money,
    PreferenceAttribute,
    PreferenceDirection,
    RankingExplanation,
    SoftPreference,
    TransactionCandidate,
)

from mandatelab_engine.constraints import evaluate_constraints


_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_ONE = Decimal("1")
_FOUR_PLACES = Decimal("0.0001")


class RankingError(ValueError):
    """Raised when profile, mandate, or candidate identities are inconsistent."""


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: TransactionCandidate
    explanation: RankingExplanation


@dataclass(frozen=True, slots=True)
class _Component:
    score: Decimal
    weight: Decimal
    influences: tuple[str, ...]


def _unit(value: Decimal) -> Decimal:
    return min(_ONE, max(_ZERO, value))


def _rounded(value: Decimal) -> Decimal:
    return _unit(value).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def _effective(weight: Decimal, confidence: Decimal) -> Decimal:
    return _unit(weight * confidence)


def _inverse(score: Decimal) -> Decimal:
    return _ONE - score


def _lower_is_better(
    values: dict[str, Decimal | None]
) -> dict[str, Decimal | None]:
    known = [value for value in values.values() if value is not None]
    if not known:
        return {candidate_id: None for candidate_id in values}
    minimum = min(known)
    maximum = max(known)
    if minimum == maximum:
        return {
            candidate_id: _ONE if value is not None else None
            for candidate_id, value in values.items()
        }
    span = maximum - minimum
    return {
        candidate_id: (
            (maximum - value) / span if value is not None else None
        )
        for candidate_id, value in values.items()
    }


def _higher_is_better(
    values: dict[str, Decimal | None]
) -> dict[str, Decimal | None]:
    known = [value for value in values.values() if value is not None]
    if not known:
        return {candidate_id: None for candidate_id in values}
    minimum = min(known)
    maximum = max(known)
    if minimum == maximum:
        return {
            candidate_id: _ONE if value is not None else None
            for candidate_id, value in values.items()
        }
    span = maximum - minimum
    return {
        candidate_id: (
            (value - minimum) / span if value is not None else None
        )
        for candidate_id, value in values.items()
    }


def _eligible(
    candidate: TransactionCandidate, mandate: Mandate
) -> bool:
    results = evaluate_constraints(mandate.hard_constraints, candidate)
    if any(result.status is not ConstraintStatus.PASS for result in results):
        return False
    price = candidate.final_landed_price
    return (
        price is not None
        and price.amount
        <= mandate.authorization.maximum_authorized_total.amount
    )


def _matches(actual: object, expected: object) -> bool:
    if isinstance(actual, Money) and isinstance(expected, Money):
        return actual.amount == expected.amount
    if isinstance(actual, date) and isinstance(expected, date):
        return actual == expected
    if isinstance(actual, str):
        if isinstance(expected, str):
            return actual.casefold() == expected.casefold()
        if isinstance(expected, list):
            return actual.casefold() in {
                str(item).casefold() for item in expected
            }
    if isinstance(actual, list):
        actual_values = {str(item).casefold() for item in actual}
        if isinstance(expected, str):
            return expected.casefold() in actual_values
        if isinstance(expected, list):
            return all(
                str(item).casefold() in actual_values for item in expected
            )
    return actual == expected


def _actual_value(
    candidate: TransactionCandidate, attribute: PreferenceAttribute
) -> object:
    if attribute is PreferenceAttribute.PRICE:
        return candidate.final_landed_price
    if attribute is PreferenceAttribute.BRAND:
        return candidate.brand
    if attribute is PreferenceAttribute.CONDITION:
        return candidate.condition.value if candidate.condition else None
    if attribute is PreferenceAttribute.DELIVERY:
        return candidate.delivery_date
    if attribute is PreferenceAttribute.RETURN_POLICY:
        return (
            candidate.return_policy.returnable
            if candidate.return_policy is not None
            else None
        )
    if attribute is PreferenceAttribute.MERCHANT_TRUST:
        return candidate.merchant
    if attribute is PreferenceAttribute.QUALITY:
        return candidate.features
    raise AssertionError(f"unsupported preference attribute: {attribute}")


def _explicit_score(
    preference: SoftPreference,
    candidate: TransactionCandidate,
    price_scores: dict[str, Decimal | None],
    delivery_scores: dict[str, Decimal | None],
    return_scores: dict[str, Decimal | None],
) -> Decimal | None:
    attribute = preference.attribute
    if preference.direction in {
        PreferenceDirection.PREFER,
        PreferenceDirection.AVOID,
    }:
        actual = _actual_value(candidate, attribute)
        matched = actual is not None and _matches(
            actual, preference.preferred_value
        )
        score = _ONE if matched else _ZERO
        return (
            score
            if preference.direction is PreferenceDirection.PREFER
            else _inverse(score)
        )

    base_score: Decimal | None = None
    if attribute is PreferenceAttribute.PRICE:
        base_score = price_scores[candidate.candidate_id]
    elif attribute is PreferenceAttribute.DELIVERY:
        base_score = delivery_scores[candidate.candidate_id]
    elif attribute is PreferenceAttribute.RETURN_POLICY:
        base_score = return_scores[candidate.candidate_id]

    if base_score is None:
        return None
    lower_is_better = attribute in {
        PreferenceAttribute.PRICE,
        PreferenceAttribute.DELIVERY,
    }
    wants_base_score = (
        lower_is_better
        and preference.direction is PreferenceDirection.MINIMIZE
    ) or (
        not lower_is_better
        and preference.direction is PreferenceDirection.MAXIMIZE
    )
    return base_score if wants_base_score else _inverse(base_score)


def _explicit_component(
    preferences: list[SoftPreference],
    candidate: TransactionCandidate,
    price_scores: dict[str, Decimal | None],
    delivery_scores: dict[str, Decimal | None],
    return_scores: dict[str, Decimal | None],
) -> _Component | None:
    scored: list[tuple[SoftPreference, Decimal, Decimal]] = []
    for preference in preferences:
        weight = _effective(preference.weight, preference.confidence)
        score = _explicit_score(
            preference,
            candidate,
            price_scores,
            delivery_scores,
            return_scores,
        )
        if weight > 0 and score is not None:
            scored.append((preference, score, weight))
    if not scored:
        return None
    total_weight = sum((item[2] for item in scored), start=_ZERO)
    score = sum(
        (item_score * item_weight for _, item_score, item_weight in scored),
        start=_ZERO,
    ) / total_weight
    return _Component(
        score=_unit(score),
        weight=_unit(total_weight),
        influences=tuple(item.preference_id for item, _, _ in scored),
    )


def _profile_components(
    candidate: TransactionCandidate,
    profile: BuyerPreferenceProfile,
    explicit_attributes: set[PreferenceAttribute],
    price_scores: dict[str, Decimal | None],
    delivery_scores: dict[str, Decimal | None],
    return_scores: dict[str, Decimal | None],
) -> dict[PreferenceAttribute, _Component]:
    components: dict[PreferenceAttribute, _Component] = {}

    importance_signals = {
        PreferenceAttribute.PRICE: (
            profile.price_sensitivity,
            price_scores[candidate.candidate_id],
            "profile:price_sensitivity",
        ),
        PreferenceAttribute.DELIVERY: (
            profile.delivery_importance,
            delivery_scores[candidate.candidate_id],
            "profile:delivery_importance",
        ),
        PreferenceAttribute.RETURN_POLICY: (
            profile.return_policy_importance,
            return_scores[candidate.candidate_id],
            "profile:return_policy_importance",
        ),
    }
    for attribute, (signal, score, influence) in importance_signals.items():
        if (
            attribute in explicit_attributes
            or signal.value is ImportanceLevel.UNKNOWN
            or score is None
        ):
            continue
        weight = _effective(signal.numeric_weight, signal.confidence)
        if weight > 0:
            components[attribute] = _Component(
                score=score, weight=weight, influences=(influence,)
            )

    if PreferenceAttribute.BRAND not in explicit_attributes:
        preferred = {
            signal.value.casefold(): signal
            for signal in profile.preferred_brands
        }
        disliked = {
            signal.value.casefold(): signal for signal in profile.disliked_brands
        }
        all_signals = [*preferred.values(), *disliked.values()]
        if all_signals:
            weight = max(
                _effective(signal.numeric_weight, signal.confidence)
                for signal in all_signals
            )
            brand = candidate.brand.casefold() if candidate.brand else None
            if brand in preferred:
                score = _ONE
                influence = f"profile:preferred_brand:{preferred[brand].value}"
            elif brand in disliked:
                score = _ZERO
                influence = f"profile:disliked_brand:{disliked[brand].value}"
            else:
                score = _HALF
                influence = "profile:brand_neutral"
            if weight > 0:
                components[PreferenceAttribute.BRAND] = _Component(
                    score=score, weight=weight, influences=(influence,)
                )

    if PreferenceAttribute.CONDITION not in explicit_attributes:
        signals = profile.condition_preferences
        if signals:
            weight = max(
                _effective(signal.numeric_weight, signal.confidence)
                for signal in signals
            )
            preferred = {signal.value for signal in signals}
            matched = candidate.condition in preferred
            score = _ONE if matched else _HALF
            influence = (
                f"profile:preferred_condition:{candidate.condition.value}"
                if matched and candidate.condition is not None
                else "profile:condition_neutral"
            )
            if weight > 0:
                components[PreferenceAttribute.CONDITION] = _Component(
                    score=score, weight=weight, influences=(influence,)
                )

    return components


def rank_candidates(
    candidates: list[TransactionCandidate],
    mandate: Mandate,
    profile: BuyerPreferenceProfile,
) -> list[RankedCandidate]:
    """Rank feasible candidates with deterministic buyer-specific weighting."""

    if profile.buyer_id != mandate.buyer_id:
        raise RankingError("profile and mandate buyer_id must match")
    if (
        profile.category != "*"
        and profile.category.casefold() != mandate.category.casefold()
    ):
        raise RankingError("profile and mandate category must match")
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise RankingError("candidate_id values must be unique")

    feasible = [
        candidate for candidate in candidates if _eligible(candidate, mandate)
    ]
    if not feasible:
        return []

    price_scores = _lower_is_better(
        {
            item.candidate_id: (
                item.final_landed_price.amount
                if item.final_landed_price is not None
                else None
            )
            for item in feasible
        }
    )
    delivery_scores = _lower_is_better(
        {
            item.candidate_id: (
                Decimal(item.delivery_date.toordinal())
                if item.delivery_date is not None
                else None
            )
            for item in feasible
        }
    )
    return_scores = _higher_is_better(
        {
            item.candidate_id: (
                Decimal(item.return_policy.window_days)
                if item.return_policy is not None
                and item.return_policy.returnable is True
                and item.return_policy.window_days is not None
                else _ZERO
                if item.return_policy is not None
                and item.return_policy.returnable is False
                else None
            )
            for item in feasible
        }
    )

    explicit_by_attribute: dict[
        PreferenceAttribute, list[SoftPreference]
    ] = {}
    for preference in mandate.soft_preferences:
        explicit_by_attribute.setdefault(preference.attribute, []).append(
            preference
        )
    explicit_attributes = set(explicit_by_attribute)

    scored: list[
        tuple[
            TransactionCandidate,
            Decimal,
            dict[PreferenceAttribute, Decimal],
            list[str],
        ]
    ] = []
    for candidate in feasible:
        components = _profile_components(
            candidate,
            profile,
            explicit_attributes,
            price_scores,
            delivery_scores,
            return_scores,
        )
        for attribute, preferences in explicit_by_attribute.items():
            component = _explicit_component(
                preferences,
                candidate,
                price_scores,
                delivery_scores,
                return_scores,
            )
            if component is not None:
                components[attribute] = component

        total_weight = sum(
            (component.weight for component in components.values()),
            start=_ZERO,
        )
        if total_weight == 0:
            total_score = _HALF
        else:
            total_score = sum(
                (
                    component.score * component.weight
                    for component in components.values()
                ),
                start=_ZERO,
            ) / total_weight
        component_scores = {
            attribute: _rounded(component.score)
            for attribute, component in components.items()
        }
        influences = list(
            dict.fromkeys(
                influence
                for component in components.values()
                for influence in component.influences
            )
        )
        scored.append(
            (candidate, _rounded(total_score), component_scores, influences)
        )

    scored.sort(key=lambda item: (-item[1], item[0].candidate_id))
    ranked: list[RankedCandidate] = []
    total = len(scored)
    for position, (candidate, score, component_scores, influences) in enumerate(
        scored, start=1
    ):
        strongest = sorted(
            component_scores.items(),
            key=lambda item: (-item[1], item[0].value),
        )[:2]
        if strongest:
            details = ", ".join(
                f"{attribute.value}={component_score}"
                for attribute, component_score in strongest
            )
            summary = (
                f"Ranked {position} of {total} for this buyer; strongest "
                f"component scores: {details}."
            )
        else:
            summary = (
                f"Ranked {position} of {total} by deterministic candidate ID "
                "because no applicable preference evidence was available."
            )
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                explanation=RankingExplanation(
                    total_score=score,
                    component_scores=component_scores,
                    influential_preferences=influences,
                    summary=summary,
                ),
            )
        )
    return ranked
