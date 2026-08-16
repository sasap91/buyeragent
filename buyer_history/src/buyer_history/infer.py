"""Turn a transaction ledger into profiles.

Everything here is deterministic: same ledger, same feedback, same `as_of` date
gives the same profiles. No model is trained and nothing is fitted numerically,
so each number can be traced back to the rows that produced it.

Evidence weighting combines two factors:
  * the workbook's per-row `Model Weight` (how trustworthy the row is), and
  * a recency half-life (how current the row still is).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from buyer_history.normalize import PREMIUM_ATTRIBUTES
from buyer_history.schema import (
    BuyerPreferenceProfile,
    CadenceSource,
    CategoryProfile,
    FeedbackEvent,
    FeedbackKind,
    Importance,
    ItemProfile,
    NormalizedTransaction,
    PreferenceSignal,
    PriceStats,
    RepeatBehavior,
    Source,
    unknown_signal,
)

DAYS_PER_MONTH = 30.44
DEFAULT_HALF_LIFE_DAYS = 270.0

# Price-sensitivity bucket edges, on a 0..1 score where higher = more sensitive.
SENSITIVITY_EDGES = (0.40, 0.62)
# Quality-importance bucket edges, higher = cares more about quality.
QUALITY_EDGES = (0.25, 0.55)


# --------------------------------------------------------------------------
# Small statistical helpers
# --------------------------------------------------------------------------


def recency_weight(when: date, as_of: date, half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Exponential decay so recent behaviour outweighs old behaviour."""
    age = max(0, (as_of - when).days)
    return 0.5 ** (age / half_life_days)


def evidence_weight(
    txn: NormalizedTransaction,
    as_of: date,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    return txn.model_weight * recency_weight(txn.purchased_on, as_of, half_life_days)


def weighted_percentile(pairs: Sequence[tuple[float, float]], quantile: float) -> float:
    """Weighted percentile over (value, weight) pairs."""
    usable = [(v, w) for v, w in pairs if w > 0]
    if not usable:
        return 0.0
    usable.sort(key=lambda pair: pair[0])
    total = sum(w for _, w in usable)
    target = quantile * total
    running = 0.0
    for value, weight in usable:
        running += weight
        if running >= target:
            return value
    return usable[-1][0]


def make_price_stats(pairs: Sequence[tuple[float, float]]) -> PriceStats:
    values = [v for v, w in pairs if w > 0]
    if not values:
        return PriceStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    total_weight = sum(w for _, w in pairs if w > 0)
    mean = sum(v * w for v, w in pairs if w > 0) / total_weight if total_weight else 0.0
    return PriceStats(
        minimum=min(values),
        p10=weighted_percentile(pairs, 0.10),
        median=weighted_percentile(pairs, 0.50),
        p90=weighted_percentile(pairs, 0.90),
        maximum=max(values),
        mean=mean,
        samples=len(values),
    )


def _confidence(evidence: float, occasions: int, evidence_scale: float = 4.0) -> float:
    """Blend "how much trustworthy evidence" with "how many separate occasions"."""
    from_evidence = 1.0 - 0.5 ** (max(evidence, 0.0) / evidence_scale)
    from_occasions = min(1.0, occasions / 4.0)
    return round(min(0.95, 0.6 * from_evidence + 0.4 * from_occasions), 4)


def _bucket(score: float, edges: tuple[float, float]) -> Importance:
    if score < edges[0]:
        return Importance.LOW
    if score < edges[1]:
        return Importance.MEDIUM
    return Importance.HIGH


# --------------------------------------------------------------------------
# Item profiles
# --------------------------------------------------------------------------


def _cadence_from_dates(dates: Sequence[date]) -> tuple[float | None, int]:
    unique = sorted(set(dates))
    if len(unique) < 2:
        return None, 0
    gaps = [(b - a).days for a, b in zip(unique, unique[1:]) if (b - a).days > 0]
    if not gaps:
        return None, 0
    return statistics.mean(gaps), len(gaps)


def build_item_profiles(
    transactions: Sequence[NormalizedTransaction],
    as_of: date,
    modeled_monthly_occasions: dict[tuple[str, str], float] | None = None,
    feedback: Sequence[FeedbackEvent] = (),
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> dict[str, ItemProfile]:
    modeled_monthly_occasions = modeled_monthly_occasions or {}
    grouped: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    for txn in transactions:
        grouped[txn.item].append(txn)

    negatives: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in feedback:
        if event.item and event.kind in (
            FeedbackKind.RETURN,
            FeedbackKind.CANCELLATION,
            FeedbackKind.RECOMMENDATION_REJECTED,
        ):
            negatives[event.item][event.kind.value] += 1

    profiles: dict[str, ItemProfile] = {}
    for item, rows in grouped.items():
        weights = [evidence_weight(t, as_of, half_life_days) for t in rows]
        total_evidence = sum(weights)
        occasions = len({t.order_id for t in rows})
        purchase_dates = [t.purchased_on for t in rows]

        price_pairs = [(t.unit_price, w) for t, w in zip(rows, weights) if t.unit_price > 0]

        # Prefer the workbook's rescaled current cadence where it exists: the
        # README states the sparse Weee! order dates understate how often the
        # household actually shops for these items now.
        cadence_days: float | None = None
        cadence_source = CadenceSource.NONE
        cadence_samples = 0
        for channel in {t.channel for t in rows}:
            modeled = modeled_monthly_occasions.get((channel, item))
            if modeled and modeled > 0:
                cadence_days = DAYS_PER_MONTH / modeled
                cadence_source = CadenceSource.MODELED_CURRENT
                cadence_samples = occasions
                break
        if cadence_days is None:
            cadence_days, cadence_samples = _cadence_from_dates(purchase_dates)
            if cadence_days is not None:
                cadence_source = CadenceSource.OBSERVED_GAPS

        last_purchased = max(purchase_dates)
        next_due = (
            last_purchased + timedelta(days=round(cadence_days)) if cadence_days else None
        )

        brand_weights: dict[str, float] = defaultdict(float)
        for txn, weight in zip(rows, weights):
            if txn.brand:
                brand_weights[txn.brand] += weight
        branded_total = sum(brand_weights.values())
        brand_shares = (
            {b: round(w / branded_total, 4) for b, w in sorted(brand_weights.items(), key=lambda kv: -kv[1])}
            if branded_total > 0
            else {}
        )

        attribute_weights: dict[str, float] = defaultdict(float)
        for txn, weight in zip(rows, weights):
            for tag in txn.attributes:
                attribute_weights[tag] += weight
        attribute_rates = (
            {t: round(w / total_evidence, 4) for t, w in sorted(attribute_weights.items(), key=lambda kv: -kv[1])}
            if total_evidence > 0
            else {}
        )

        if occasions >= 3:
            repeat = RepeatBehavior.RECURRING
        elif occasions == 2:
            repeat = RepeatBehavior.REPEAT
        else:
            repeat = RepeatBehavior.ONE_OFF

        profiles[item] = ItemProfile(
            item=item,
            categories=sorted({t.category for t in rows}),
            channels=sorted({t.channel for t in rows}),
            occasions=occasions,
            total_quantity=round(sum(t.quantity for t in rows), 3),
            total_spend=round(sum(t.line_spend for t in rows), 2),
            unit_price=make_price_stats(price_pairs),
            first_purchased=min(purchase_dates),
            last_purchased=last_purchased,
            repeat_behavior=repeat,
            cadence_days=round(cadence_days, 2) if cadence_days else None,
            cadence_source=cadence_source,
            cadence_samples=cadence_samples,
            next_due_on=next_due,
            brand_shares=brand_shares,
            attribute_rates=attribute_rates,
            evidence_weight=round(total_evidence, 4),
            confidence=_confidence(total_evidence, occasions, evidence_scale=3.0),
            negative_signals=dict(negatives.get(item, {})),
        )

    return profiles


# --------------------------------------------------------------------------
# Price sensitivity and quality importance
# --------------------------------------------------------------------------


def _price_move_tolerance(
    rows: Sequence[NormalizedTransaction],
) -> tuple[float | None, int, list[str]]:
    """How the buyer reacts when a repeat item's price moves.

    Every observed transition is by definition a repurchase, so the question is
    which direction the price was moving when they kept buying. Consistently
    repurchasing into a rising price means the category tolerates price; a
    pattern of stepping down to cheaper options means it does not.
    """
    by_item: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    for txn in rows:
        if txn.unit_price > 0:
            by_item[txn.item].append(txn)

    up = down = flat = 0
    notes: list[str] = []
    for item, txns in by_item.items():
        txns = sorted(txns, key=lambda t: t.purchased_on)
        for previous, current in zip(txns, txns[1:]):
            change = (current.unit_price - previous.unit_price) / previous.unit_price
            if change > 0.05:
                up += 1
                notes.append(
                    f"{item}: repurchased at ${current.unit_price:.2f} "
                    f"after ${previous.unit_price:.2f} (+{change:.0%})"
                )
            elif change < -0.05:
                down += 1
                notes.append(
                    f"{item}: stepped down to ${current.unit_price:.2f} "
                    f"from ${previous.unit_price:.2f} ({change:.0%})"
                )
            else:
                flat += 1

    transitions = up + down + flat
    if transitions == 0:
        return None, 0, []
    tolerance = (up + 0.5 * flat) / transitions
    return tolerance, transitions, notes[:4]


def _within_item_dispersion(rows: Sequence[NormalizedTransaction]) -> float | None:
    """Mean coefficient of variation of unit price, computed per item.

    Measured within an item rather than across the category, so genuinely
    different products (green onions vs jasmine rice) do not read as volatility.
    """
    by_item: dict[str, list[float]] = defaultdict(list)
    for txn in rows:
        if txn.unit_price > 0:
            by_item[txn.item].append(txn.unit_price)

    coefficients = [
        statistics.pstdev(prices) / statistics.mean(prices)
        for prices in by_item.values()
        if len(prices) >= 2 and statistics.mean(prices) > 0
    ]
    return statistics.mean(coefficients) if coefficients else None


def _premium_rate(rows: Sequence[NormalizedTransaction], weights: Sequence[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    premium = sum(
        weight
        for txn, weight in zip(rows, weights)
        if PREMIUM_ATTRIBUTES.intersection(txn.attributes)
    )
    return premium / total


def _brand_loyalty(
    rows: Sequence[NormalizedTransaction], weights: Sequence[float]
) -> tuple[float, float, str | None, dict[str, float]]:
    """Returns (loyalty, branded_rate, top_brand, shares)."""
    total = sum(weights)
    brand_weights: dict[str, float] = defaultdict(float)
    for txn, weight in zip(rows, weights):
        if txn.brand:
            brand_weights[txn.brand] += weight
    branded_total = sum(brand_weights.values())
    if total <= 0 or branded_total <= 0:
        return 0.0, 0.0, None, {}
    shares = {b: w / branded_total for b, w in brand_weights.items()}
    top_brand = max(shares, key=lambda b: shares[b])
    branded_rate = branded_total / total
    return branded_rate * shares[top_brand], branded_rate, top_brand, shares


def price_sensitivity_signal(
    rows: Sequence[NormalizedTransaction],
    weights: Sequence[float],
    label: str,
) -> PreferenceSignal:
    """Deterministic, decomposable price sensitivity.

    Blends three observable components; the returned evidence lists each one so
    the ranking explanation can quote them directly.
    """
    tolerance, transitions, move_notes = _price_move_tolerance(rows)
    dispersion = _within_item_dispersion(rows)
    premium = _premium_rate(rows, weights)

    tolerance_component = 1.0 - (tolerance if tolerance is not None else 0.5)
    dispersion_component = min(1.0, (dispersion if dispersion is not None else 0.25) / 0.5)
    premium_component = 1.0 - premium

    score = 0.40 * tolerance_component + 0.35 * dispersion_component + 0.25 * premium_component
    bucket = _bucket(score, SENSITIVITY_EDGES)

    evidence = [
        f"score {score:.2f} for {label}",
        (
            f"price-move tolerance {tolerance:.2f} over {transitions} repurchase "
            f"transitions (higher = keeps buying as price rises)"
            if tolerance is not None
            else "no repeat purchases to measure price-move tolerance; used a neutral 0.50"
        ),
        (
            f"within-item price dispersion {dispersion:.2f}"
            if dispersion is not None
            else "no repeated item to measure price dispersion; used a neutral 0.25"
        ),
        f"premium-attribute rate {premium:.2f} of weighted spend lines",
    ]
    evidence.extend(move_notes)

    # Confidence tracks how much of the score rests on real repurchase evidence.
    measured = sum(1 for value in (tolerance, dispersion) if value is not None)
    confidence = _confidence(sum(weights), transitions + measured, evidence_scale=4.0)
    if measured == 0:
        confidence = min(confidence, 0.30)

    return PreferenceSignal(
        value=bucket,
        source=Source.INFERRED,
        confidence=confidence,
        evidence=evidence,
    )


def quality_importance_signal(
    rows: Sequence[NormalizedTransaction],
    weights: Sequence[float],
    label: str,
) -> PreferenceSignal:
    premium = _premium_rate(rows, weights)
    loyalty, branded_rate, top_brand, _ = _brand_loyalty(rows, weights)
    score = 0.6 * premium + 0.4 * loyalty
    bucket = _bucket(score, QUALITY_EDGES)

    evidence = [
        f"score {score:.2f} for {label}",
        f"premium-attribute rate {premium:.2f} (organic, grass-fed, cage-free, wild-caught, non-GMO)",
        f"brand loyalty {loyalty:.2f} (branded rate {branded_rate:.2f})",
    ]
    if top_brand:
        evidence.append(f"most repeated brand: {top_brand}")

    return PreferenceSignal(
        value=bucket,
        source=Source.INFERRED,
        confidence=_confidence(sum(weights), len({t.order_id for t in rows})),
        evidence=evidence,
    )


def brand_loyalty_signal(
    rows: Sequence[NormalizedTransaction],
    weights: Sequence[float],
) -> PreferenceSignal:
    loyalty, branded_rate, top_brand, shares = _brand_loyalty(rows, weights)
    evidence = [
        f"branded line rate {branded_rate:.2f}",
        f"top-brand share of branded lines {max(shares.values()):.2f}" if shares else "no branded lines",
    ]
    if branded_rate < 0.20:
        evidence.append(
            "mostly unbranded commodity goods; brand is unlikely to drive this category"
        )
    return PreferenceSignal(
        value={
            "loyalty": round(loyalty, 4),
            "branded_rate": round(branded_rate, 4),
            "top_brand": top_brand,
            "shares": {b: round(s, 4) for b, s in sorted(shares.items(), key=lambda kv: -kv[1])},
        },
        source=Source.OBSERVED,
        confidence=_confidence(sum(weights), len({t.order_id for t in rows})),
        evidence=evidence,
    )


# --------------------------------------------------------------------------
# Category profiles
# --------------------------------------------------------------------------


def build_category_profiles(
    transactions: Sequence[NormalizedTransaction],
    as_of: date,
    modeled_category_occasions: dict[tuple[str, str], float] | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> dict[str, CategoryProfile]:
    modeled_category_occasions = modeled_category_occasions or {}

    orders_per_channel: dict[str, set[str]] = defaultdict(set)
    all_orders: set[str] = set()
    for txn in transactions:
        orders_per_channel[txn.channel].add(txn.order_id)
        all_orders.add(txn.order_id)

    total_spend = sum(t.line_spend for t in transactions) or 1.0

    grouped: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    for txn in transactions:
        grouped[txn.category].append(txn)

    profiles: dict[str, CategoryProfile] = {}
    for category, rows in grouped.items():
        weights = [evidence_weight(t, as_of, half_life_days) for t in rows]
        total_evidence = sum(weights)
        orders_with_category = len({t.order_id for t in rows})
        channels = sorted({t.channel for t in rows})

        penetration_by_channel = {}
        for channel in channels:
            channel_orders = orders_per_channel[channel]
            in_category = {t.order_id for t in rows if t.channel == channel}
            penetration_by_channel[channel] = (
                round(len(in_category) / len(channel_orders), 4) if channel_orders else 0.0
            )

        monthly_occasions = None
        cadence_source = CadenceSource.NONE
        for channel in channels:
            modeled = modeled_category_occasions.get((channel, category))
            if modeled and modeled > 0:
                monthly_occasions = modeled
                cadence_source = CadenceSource.MODELED_CURRENT
                break
        if monthly_occasions is None:
            observed_dates = sorted({t.purchased_on for t in rows})
            if len(observed_dates) >= 2:
                span_days = (observed_dates[-1] - observed_dates[0]).days
                if span_days > 0:
                    monthly_occasions = round(
                        len(observed_dates) / (span_days / DAYS_PER_MONTH), 3
                    )
                    cadence_source = CadenceSource.OBSERVED_GAPS

        spend = sum(t.line_spend for t in rows)
        item_totals: dict[str, float] = defaultdict(float)
        for txn, weight in zip(rows, weights):
            item_totals[txn.item] += weight

        preferred_channel = None
        if channels:
            channel_weight: dict[str, float] = defaultdict(float)
            for txn, weight in zip(rows, weights):
                channel_weight[txn.channel] += weight
            preferred_channel = max(channel_weight, key=lambda c: channel_weight[c])

        profiles[category] = CategoryProfile(
            category=category,
            channels=channels,
            orders_with_category=orders_with_category,
            penetration_household=round(orders_with_category / len(all_orders), 4)
            if all_orders
            else 0.0,
            penetration_by_channel=penetration_by_channel,
            line_items=len(rows),
            unique_items=len({t.item for t in rows}),
            total_quantity=round(sum(t.quantity for t in rows), 3),
            total_spend=round(spend, 2),
            spend_share=round(spend / total_spend, 4),
            unit_price=make_price_stats(
                [(t.unit_price, w) for t, w in zip(rows, weights) if t.unit_price > 0]
            ),
            first_purchased=min(t.purchased_on for t in rows),
            last_purchased=max(t.purchased_on for t in rows),
            monthly_occasions=monthly_occasions,
            cadence_source=cadence_source,
            price_sensitivity=price_sensitivity_signal(rows, weights, category),
            quality_importance=quality_importance_signal(rows, weights, category),
            brand_loyalty=brand_loyalty_signal(rows, weights),
            top_items=[i for i, _ in sorted(item_totals.items(), key=lambda kv: -kv[1])[:5]],
            preferred_channel=preferred_channel,
            evidence_weight=round(total_evidence, 4),
            confidence=_confidence(total_evidence, orders_with_category),
        )

    return profiles


# --------------------------------------------------------------------------
# BuyerPreferenceProfile assembly
# --------------------------------------------------------------------------

_CONDITION_UNKNOWN_REASON = (
    "No line in the source history states a product condition. Grocery and "
    "household consumables carry no new/used/refurbished attribute, so condition "
    "preference is genuinely unobservable here and must not be assumed."
)

_RETURNS_UNKNOWN_REASON = (
    "The ledger contains no returns or cancellations, so return-policy "
    "importance cannot be inferred. Absence of returns is not evidence that "
    "returns do not matter."
)

_DELIVERY_UNKNOWN_REASON = (
    "No delivery-speed or delivery-date attribute exists in the source data. "
    "The channel split (shelf-stable via Amazon, fresh via in-person Asian "
    "grocery) hints at differing urgency by category, but that is too weak to "
    "score as a preference."
)


def _disliked_brands_signal(
    feedback: Sequence[FeedbackEvent], evidence_total: float
) -> PreferenceSignal:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in feedback:
        if not event.brand:
            continue
        if event.kind in (
            FeedbackKind.RETURN,
            FeedbackKind.CANCELLATION,
            FeedbackKind.RECOMMENDATION_REJECTED,
        ):
            counts[event.brand][event.kind.value] += 1

    ranked = sorted(counts.items(), key=lambda kv: -sum(kv[1].values()))
    value = [{"brand": brand, "signals": dict(kinds)} for brand, kinds in ranked]
    evidence = (
        [f"{brand}: {sum(kinds.values())} negative feedback event(s)" for brand, kinds in ranked]
        if ranked
        else ["no returns, cancellations or rejected recommendations recorded yet"]
    )
    return PreferenceSignal(
        value=value,
        source=Source.OBSERVED,
        confidence=_confidence(evidence_total, len(ranked)) if ranked else 0.0,
        evidence=evidence,
    )


def build_preference_profile(
    buyer_id: str,
    rows: Sequence[NormalizedTransaction],
    as_of: date,
    item_profiles: dict[str, ItemProfile],
    category: str | None = None,
    feedback: Sequence[FeedbackEvent] = (),
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> BuyerPreferenceProfile:
    """Assemble the shared contract for one category, or for the buyer overall."""
    weights = [evidence_weight(t, as_of, half_life_days) for t in rows]
    total_evidence = sum(weights)
    label = category or "all categories"
    orders = len({t.order_id for t in rows})

    price_stats = make_price_stats(
        [(t.unit_price, w) for t, w in zip(rows, weights) if t.unit_price > 0]
    )

    # Brands the buyer returns to, ranked by weighted evidence.
    brand_weights: dict[str, float] = defaultdict(float)
    brand_orders: dict[str, set[str]] = defaultdict(set)
    for txn, weight in zip(rows, weights):
        if txn.brand:
            brand_weights[txn.brand] += weight
            brand_orders[txn.brand].add(txn.order_id)
    branded_total = sum(brand_weights.values())
    preferred = [
        {
            "brand": brand,
            "share": round(weight / branded_total, 4) if branded_total else 0.0,
            "occasions": len(brand_orders[brand]),
        }
        for brand, weight in sorted(brand_weights.items(), key=lambda kv: -kv[1])
        if len(brand_orders[brand]) >= 2
    ]

    channel_weights: dict[str, float] = defaultdict(float)
    channel_orders: dict[str, set[str]] = defaultdict(set)
    for txn, weight in zip(rows, weights):
        channel_weights[txn.channel] += weight
        channel_orders[txn.channel].add(txn.order_id)
    channel_total = sum(channel_weights.values()) or 1.0
    channel_value = {
        channel: {
            "share": round(weight / channel_total, 4),
            "orders": len(channel_orders[channel]),
        }
        for channel, weight in sorted(channel_weights.items(), key=lambda kv: -kv[1])
    }

    scoped_items = {
        name: profile
        for name, profile in item_profiles.items()
        if category is None or category in profile.categories
    }
    behaviour_counts = {kind.value: 0 for kind in RepeatBehavior}
    for profile in scoped_items.values():
        behaviour_counts[profile.repeat_behavior.value] += 1
    recurring = [p for p in scoped_items.values() if p.repeat_behavior is RepeatBehavior.RECURRING]
    recurring.sort(key=lambda p: -p.occasions)

    cadences = [p.cadence_days for p in scoped_items.values() if p.cadence_days]
    cadence_signal = (
        PreferenceSignal(
            value={
                "median_days": round(statistics.median(cadences), 2),
                "items_with_cadence": len(cadences),
                "top_recurring": [
                    {
                        "item": p.item,
                        "cadence_days": p.cadence_days,
                        "cadence_source": p.cadence_source.value,
                        "next_due_on": p.next_due_on.isoformat() if p.next_due_on else None,
                    }
                    for p in recurring[:5]
                ],
            },
            source=Source.OBSERVED,
            confidence=_confidence(total_evidence, len(cadences)),
            evidence=[
                f"{len(cadences)} item(s) in {label} have a measurable repurchase cadence",
                "Weee!/H Mart items use the workbook's rescaled current cadence, "
                "not the sparse historical order gaps",
            ],
        )
        if cadences
        else PreferenceSignal(
            value={"median_days": None, "items_with_cadence": 0, "top_recurring": []},
            source=Source.DEFAULT,
            confidence=0.0,
            evidence=[f"no item in {label} has been purchased on two separate dates"],
        )
    )

    return BuyerPreferenceProfile(
        buyer_id=buyer_id,
        category=category,
        price_sensitivity=price_sensitivity_signal(rows, weights, label),
        observed_price_range=PreferenceSignal(
            value=price_stats.to_dict(),
            source=Source.OBSERVED,
            confidence=_confidence(total_evidence, price_stats.samples),
            evidence=[
                f"{price_stats.samples} priced line item(s) in {label}",
                f"typical unit price band ${price_stats.p10:.2f}-${price_stats.p90:.2f}",
            ],
        ),
        quality_importance=quality_importance_signal(rows, weights, label),
        delivery_importance=unknown_signal(_DELIVERY_UNKNOWN_REASON),
        returns_importance=unknown_signal(_RETURNS_UNKNOWN_REASON),
        preferred_brands=PreferenceSignal(
            value=preferred,
            source=Source.OBSERVED,
            confidence=_confidence(total_evidence, len(preferred)) if preferred else 0.0,
            evidence=(
                [f"{b['brand']}: {b['occasions']} separate orders" for b in preferred[:5]]
                if preferred
                else [f"no brand purchased on two separate occasions in {label}"]
            ),
        ),
        disliked_brands=_disliked_brands_signal(feedback, total_evidence),
        condition_preference=unknown_signal(_CONDITION_UNKNOWN_REASON),
        channel_preference=PreferenceSignal(
            value=channel_value,
            source=Source.OBSERVED,
            confidence=_confidence(total_evidence, orders),
            evidence=[
                f"{channel}: {info['orders']} order(s), {info['share']:.0%} of weighted evidence"
                for channel, info in channel_value.items()
            ],
        ),
        repeat_behavior=PreferenceSignal(
            value={
                "counts": behaviour_counts,
                "top_recurring_items": [
                    {"item": p.item, "occasions": p.occasions} for p in recurring[:8]
                ],
            },
            source=Source.OBSERVED,
            confidence=_confidence(total_evidence, len(scoped_items)),
            evidence=[
                f"{behaviour_counts[RepeatBehavior.RECURRING.value]} recurring, "
                f"{behaviour_counts[RepeatBehavior.REPEAT.value]} repeat, "
                f"{behaviour_counts[RepeatBehavior.ONE_OFF.value]} one-off item(s) in {label}"
            ],
        ),
        replenishment_cadence_days=cadence_signal,
        confidence=_confidence(total_evidence, orders),
        notes=[
            "Learned from purchase history. Evidence only, never a hard mandate.",
            "Current explicit intent overrides every value in this profile.",
        ],
    )


def resolve_category_key(
    category: str | None,
    known: Iterable[str],
) -> str | None:
    """Best match for a candidate's category against the learned category keys.

    Tries an exact match, then a leaf match ("Coffee" vs "Groceries > Coffee"),
    then a top-level match. Returns None when the buyer has no history in
    anything resembling the category, which is itself useful information.
    """
    if not category:
        return None
    known = list(known)
    if category in known:
        return category

    def leaf(value: str) -> str:
        return value.split(">")[-1].strip().lower()

    def top(value: str) -> str:
        return value.split(">")[0].strip().lower()

    for key in known:
        if leaf(key) == leaf(category):
            return key
    for key in known:
        if top(key) == top(category) and top(category):
            return key
    return None
