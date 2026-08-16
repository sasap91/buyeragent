"""Weekly basket suggestions.

Turns a learned profile into "here is what this household needs to buy this
week". The profile answers *what would they want*; this answers *what do they
need now, how much, and roughly what will it cost*.

An item is suggested when its replenishment cycle comes due inside the horizon.
Each suggestion carries the reasons behind it, so the list can be defended item
by item rather than taken on trust.

Suggestions are exactly that. Nothing here authorizes a purchase -- the Mandate
Engine owns that decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from buyer_history.predict import predict_purchase_probability
from buyer_history.schema import (
    BuyerProfileBundle,
    CadenceSource,
    ItemProfile,
    PredictionContext,
    PurchaseCandidate,
    RepeatBehavior,
    jsonify,
)

# Beyond this many cycles, a modeled cadence means "trips we never recorded",
# not "overdue". Those items are treated as due-now staples instead of being
# reported as hundreds of days late.
UNRECORDED_TRIP_CYCLES = 3.0


@dataclass
class BasketSuggestion:
    """One suggested line, with the reasoning that produced it."""

    item: str
    category: str
    channel: str
    quantity: float
    estimated_unit_price: float
    estimated_line_total: float
    due_on: date | None
    days_until_due: int | None
    cadence_days: float | None
    cadence_source: str
    occasions: int
    probability: float
    confidence: float
    brand: str | None = None
    search_query: str = ""
    status: str = "DUE"  # DUE | OVERDUE | UPCOMING | STAPLE
    reasons: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonify(self)


@dataclass
class WeeklyBasket:
    buyer_id: str
    as_of: date
    horizon_days: int
    suggestions: list[BasketSuggestion] = field(default_factory=list)
    profile_version: int = 0

    @property
    def estimated_total(self) -> float:
        return round(sum(s.estimated_line_total for s in self.suggestions), 2)

    def by_channel(self) -> dict[str, list[BasketSuggestion]]:
        grouped: dict[str, list[BasketSuggestion]] = {}
        for suggestion in self.suggestions:
            grouped.setdefault(suggestion.channel, []).append(suggestion)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "buyer_id": self.buyer_id,
            "as_of": self.as_of.isoformat(),
            "horizon_days": self.horizon_days,
            "profile_version": self.profile_version,
            "estimated_total": self.estimated_total,
            "count": len(self.suggestions),
            "by_channel": {
                channel: [s.to_dict() for s in items]
                for channel, items in self.by_channel().items()
            },
            "suggestions": [s.to_dict() for s in self.suggestions],
        }


def _typical_quantity(profile: ItemProfile) -> float:
    if profile.occasions <= 0:
        return 1.0
    quantity = profile.total_quantity / profile.occasions
    return max(1.0, round(quantity))


def _preferred_brand(profile: ItemProfile) -> str | None:
    return next(iter(profile.brand_shares), None) if profile.brand_shares else None


def _due_state(
    profile: ItemProfile,
    as_of: date,
    horizon_days: int,
) -> tuple[bool, str, date | None, int | None]:
    """Decide whether an item falls inside the horizon, and how to label it."""
    if not profile.cadence_days or not profile.next_due_on:
        return False, "", None, None

    days_since = (as_of - profile.last_purchased).days
    cycles = days_since / profile.cadence_days

    # A modeled cadence describes how often the household shops now, but not
    # every one of those trips is in the ledger. A gap many cycles wide means
    # unrecorded purchases, so the item is a standing staple rather than
    # dramatically overdue.
    if profile.cadence_source is CadenceSource.MODELED_CURRENT and cycles > UNRECORDED_TRIP_CYCLES:
        return True, "STAPLE", as_of, 0

    days_until = (profile.next_due_on - as_of).days
    if days_until < 0:
        return True, "OVERDUE", profile.next_due_on, days_until
    if days_until <= horizon_days:
        return True, "DUE", profile.next_due_on, days_until
    return False, "UPCOMING", profile.next_due_on, days_until


def suggest_weekly_basket(
    bundle: BuyerProfileBundle,
    as_of: date | None = None,
    horizon_days: int = 7,
    limit: int | None = None,
    include_one_offs: bool = False,
) -> WeeklyBasket:
    """Build the shopping list for the coming `horizon_days`.

    Only items with an established repurchase rhythm are suggested; a product
    bought once is a past decision, not a recurring need.
    """
    as_of = as_of or bundle.as_of
    context = PredictionContext(as_of=as_of)
    basket = WeeklyBasket(
        buyer_id=bundle.buyer_id,
        as_of=as_of,
        horizon_days=horizon_days,
        profile_version=bundle.version,
    )

    for profile in bundle.item_profiles.values():
        if not include_one_offs and profile.repeat_behavior is RepeatBehavior.ONE_OFF:
            continue

        due, status, due_on, days_until = _due_state(profile, as_of, horizon_days)
        if not due:
            continue

        quantity = _typical_quantity(profile)
        unit_price = profile.unit_price.median or profile.unit_price.mean
        channel = profile.channels[0] if profile.channels else ""
        category = profile.categories[0] if profile.categories else ""
        brand = _preferred_brand(profile)

        prediction = predict_purchase_probability(
            bundle,
            PurchaseCandidate(
                candidate_id=f"basket:{profile.item}",
                item=profile.item,
                category=category,
                unit_price=unit_price,
                brand=brand,
                channel=channel,
                quantity=quantity,
            ),
            context,
        )

        reasons = [f"{d.name}: {d.explanation}" for d in prediction.positive_drivers[:3]]
        if status == "STAPLE":
            reasons.insert(
                0,
                f"bought on {profile.occasions} separate trips at roughly "
                f"{profile.cadence_days:.0f}-day intervals",
            )

        basket.suggestions.append(
            BasketSuggestion(
                item=profile.item,
                category=category,
                channel=channel,
                quantity=quantity,
                estimated_unit_price=round(unit_price, 2),
                estimated_line_total=round(unit_price * quantity, 2),
                due_on=due_on,
                days_until_due=days_until,
                cadence_days=profile.cadence_days,
                cadence_source=profile.cadence_source.value,
                occasions=profile.occasions,
                probability=round(prediction.probability, 4),
                confidence=round(prediction.confidence, 4),
                brand=brand,
                search_query=(profile.raw_variants[0] if profile.raw_variants else profile.item),
                status=status,
                reasons=reasons,
                unknowns=prediction.unknowns,
            )
        )

    status_rank = {"OVERDUE": 0, "STAPLE": 1, "DUE": 2, "UPCOMING": 3}
    basket.suggestions.sort(
        key=lambda s: (status_rank.get(s.status, 9), -s.probability, s.item)
    )
    if limit is not None:
        basket.suggestions = basket.suggestions[:limit]

    return basket


def format_basket(basket: WeeklyBasket) -> str:
    """Plain-text shopping list, grouped by where to buy it."""
    lines = [
        f"Weekly basket for {basket.buyer_id} -- week of {basket.as_of.isoformat()}",
        f"{len(basket.suggestions)} item(s), estimated ${basket.estimated_total:.2f} "
        f"(profile v{basket.profile_version})",
    ]
    for channel, items in basket.by_channel().items():
        subtotal = sum(s.estimated_line_total for s in items)
        lines.append(f"\n{channel} -- {len(items)} item(s), ${subtotal:.2f}")
        for suggestion in items:
            quantity = (
                f"{suggestion.quantity:g}x " if suggestion.quantity != 1 else "    "
            )
            lines.append(
                f"  {quantity}{suggestion.item:<24} "
                f"${suggestion.estimated_line_total:>6.2f}  "
                f"[{suggestion.status}] P(buy)={suggestion.probability:.2f}"
            )
    return "\n".join(lines)
