"""Explainable purchase-likelihood prediction.

`predict_purchase_probability` is a transparent additive model in log-odds
space: a base rate plus a set of named, signed contributions. There is no
fitted weight vector, so every driver can be printed with the reason it fired
and the ranking explanation the PRD requires falls out for free.

Probability and confidence are deliberately separate. A candidate can be very
likely to suit the buyer while the profile behind that judgement is thin, and a
mandate needs to be able to tell those apart.
"""

from __future__ import annotations

import math
from datetime import date

from buyer_history.infer import resolve_category_key
from buyer_history.normalize import PREMIUM_ATTRIBUTES
from buyer_history.schema import (
    BuyerProfileBundle,
    CadenceSource,
    CategoryProfile,
    Condition,
    Driver,
    Importance,
    ItemProfile,
    PredictionContext,
    PurchaseCandidate,
    PurchasePrediction,
    RepeatBehavior,
)

BASE_LOG_ODDS = -1.10

SENSITIVITY_MULTIPLIER = {
    Importance.LOW: 0.5,
    Importance.MEDIUM: 1.0,
    Importance.HIGH: 1.6,
    Importance.UNKNOWN: 1.0,
}


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _find_item_profile(bundle: BuyerProfileBundle, item: str) -> ItemProfile | None:
    if item in bundle.item_profiles:
        return bundle.item_profiles[item]
    lowered = item.strip().lower()
    for name, profile in bundle.item_profiles.items():
        if name.strip().lower() == lowered:
            return profile
    return None


def _effective_penetration(profile: CategoryProfile, channel: str | None) -> float:
    if channel and channel in profile.penetration_by_channel:
        return profile.penetration_by_channel[channel]
    by_channel = max(profile.penetration_by_channel.values(), default=0.0)
    return max(profile.penetration_household, by_channel)


def predict_purchase_probability(
    profile: BuyerProfileBundle,
    candidate: PurchaseCandidate,
    context: PredictionContext | None = None,
) -> PurchasePrediction:
    """Estimate P(this buyer buys this candidate) with a full driver breakdown."""
    context = context or PredictionContext(as_of=profile.as_of)
    as_of: date = context.as_of
    channel = candidate.channel or context.channel

    drivers: list[Driver] = []
    unknowns: list[str] = []

    item_profile = _find_item_profile(profile, candidate.item)
    category_key = resolve_category_key(candidate.category, profile.category_profiles.keys())
    category_profile = profile.category_profiles.get(category_key) if category_key else None
    preference = profile.profile_for(category_key)

    # --- explicit intent, which outranks everything learned ------------------
    explicit = dict(context.explicit_preferences or {})

    max_price = explicit.get("max_price")
    if isinstance(max_price, (int, float)) and candidate.unit_price > max_price:
        drivers.append(
            Driver(
                "explicit_intent:max_price",
                -2.2,
                f"stated max ${max_price:.2f}, candidate is ${candidate.unit_price:.2f}; "
                "explicit intent overrides learned price behaviour "
                "(the Mandate Engine owns enforcement, this is ranking only)",
            )
        )

    wanted_brands = {str(b).lower() for b in explicit.get("preferred_brands", []) or []}
    if wanted_brands and candidate.brand and candidate.brand.lower() in wanted_brands:
        drivers.append(
            Driver(
                "explicit_intent:preferred_brand",
                1.0,
                f"buyer explicitly asked for {candidate.brand} in this request",
            )
        )

    avoid_brands = {str(b).lower() for b in explicit.get("avoid_brands", []) or []}
    if avoid_brands and candidate.brand and candidate.brand.lower() in avoid_brands:
        drivers.append(
            Driver(
                "explicit_intent:avoided_brand",
                -2.0,
                f"buyer explicitly excluded {candidate.brand} in this request",
            )
        )

    required = [str(a) for a in explicit.get("required_attributes", []) or []]
    missing = [a for a in required if a not in candidate.attributes]
    if missing:
        drivers.append(
            Driver(
                "explicit_intent:missing_attribute",
                -1.2,
                f"request asked for {', '.join(required)}; candidate lacks {', '.join(missing)}",
            )
        )

    # --- item affinity -------------------------------------------------------
    if item_profile:
        contribution = min(2.2, 0.9 * math.log1p(item_profile.occasions))
        drivers.append(
            Driver(
                "item_affinity",
                contribution,
                f"bought {item_profile.occasions}x, last on "
                f"{item_profile.last_purchased.isoformat()}",
            )
        )
    else:
        unknowns.append(f"no purchase history for item '{candidate.item}'")

    # --- category affinity ---------------------------------------------------
    if category_profile:
        penetration = _effective_penetration(category_profile, channel)
        drivers.append(
            Driver(
                "category_affinity",
                2.4 * penetration - 0.30,
                f"'{category_profile.category}' appears in {penetration:.0%} of orders "
                f"({category_profile.orders_with_category} order(s))",
            )
        )
    else:
        drivers.append(
            Driver(
                "category_affinity",
                -0.70,
                f"no purchase history in anything resembling '{candidate.category}'",
            )
        )
        unknowns.append(
            f"category '{candidate.category}' is outside observed history; "
            "scored from the general profile with transfer-discounted confidence"
        )

    # --- price fit -----------------------------------------------------------
    if item_profile and item_profile.unit_price.samples >= 2:
        reference = item_profile.unit_price
        reference_label = f"item '{item_profile.item}'"
    elif category_profile:
        reference = category_profile.unit_price
        reference_label = f"category '{category_profile.category}'"
    else:
        reference = None
        reference_label = ""

    sensitivity = (
        category_profile.price_sensitivity.value
        if category_profile
        else preference.price_sensitivity.value
    )
    if not isinstance(sensitivity, Importance):
        sensitivity = Importance.UNKNOWN
    multiplier = SENSITIVITY_MULTIPLIER[sensitivity]

    if reference and reference.median > 0:
        deviation = (candidate.unit_price - reference.median) / reference.median
        if deviation <= 0.02:
            drivers.append(
                Driver(
                    "price_fit",
                    min(0.60, -deviation * 1.2),
                    f"${candidate.unit_price:.2f} at or under the ${reference.median:.2f} "
                    f"median for {reference_label} (band ${reference.p10:.2f}-${reference.p90:.2f})",
                )
            )
        else:
            drivers.append(
                Driver(
                    "price_fit",
                    -multiplier * min(2.5, deviation * 1.8),
                    f"${candidate.unit_price:.2f} is {deviation:+.0%} vs the "
                    f"${reference.median:.2f} median for {reference_label}; "
                    f"price sensitivity here is {sensitivity.value}",
                )
            )
        if candidate.unit_price > reference.maximum * 1.5 and reference.maximum > 0:
            unknowns.append(
                f"${candidate.unit_price:.2f} exceeds anything the buyer has paid "
                f"for {reference_label} (max ${reference.maximum:.2f}) -- outside observed range"
            )
    else:
        unknowns.append("no comparable price history; price fit not scored")

    # --- brand fit -----------------------------------------------------------
    disliked = {
        str(entry.get("brand", "")).lower()
        for entry in (preference.disliked_brands.value or [])
        if isinstance(entry, dict)
    }
    branded_rate = 0.0
    if category_profile and isinstance(category_profile.brand_loyalty.value, dict):
        branded_rate = float(category_profile.brand_loyalty.value.get("branded_rate") or 0.0)

    if candidate.brand and candidate.brand.lower() in disliked:
        drivers.append(
            Driver(
                "brand_fit",
                -1.6,
                f"{candidate.brand} carries negative feedback (return or rejected recommendation)",
            )
        )
    elif candidate.brand and item_profile and item_profile.brand_shares:
        share = item_profile.brand_shares.get(candidate.brand, 0.0)
        if share >= 0.4:
            drivers.append(
                Driver(
                    "brand_fit",
                    0.8 * share,
                    f"{candidate.brand} accounts for {share:.0%} of this item's purchases",
                )
            )
        else:
            drivers.append(
                Driver(
                    "brand_fit",
                    -0.30,
                    f"buyer usually picks {next(iter(item_profile.brand_shares))} for this item, "
                    f"not {candidate.brand}",
                )
            )
    elif branded_rate < 0.20 and category_profile:
        drivers.append(
            Driver(
                "brand_fit",
                0.0,
                f"only {branded_rate:.0%} of '{category_profile.category}' lines are branded; "
                "brand does not differentiate here",
            )
        )
    elif candidate.brand and branded_rate >= 0.50:
        drivers.append(
            Driver(
                "brand_fit",
                -0.40,
                f"{candidate.brand} is unseen in a category where the buyer usually sticks to brands",
            )
        )
    elif not candidate.brand:
        unknowns.append("candidate has no brand stated")

    # --- replenishment timing ------------------------------------------------
    if item_profile and item_profile.cadence_days:
        days_since = (as_of - item_profile.last_purchased).days
        ratio = days_since / item_profile.cadence_days
        cadence_note = (
            f"{days_since}d since last purchase against a "
            f"{item_profile.cadence_days:.0f}d cycle ({item_profile.cadence_source.value})"
        )
        # A modeled cadence describes how often the household shops now, but the
        # trips it describes are not all in the ledger (the workbook states H Mart
        # receipts were never captured). A gap many cycles wide therefore means
        # "purchases we cannot see", not "long overdue" -- so the restock bonus is
        # damped rather than maxed out.
        if item_profile.cadence_source is CadenceSource.MODELED_CURRENT and ratio > 3.0:
            drivers.append(
                Driver(
                    "replenishment_due",
                    0.60,
                    f"cadence prior suggests due, but {cadence_note}",
                )
            )
            unknowns.append(
                f"'{item_profile.item}' last recorded {days_since}d ago against a "
                f"{item_profile.cadence_days:.0f}d modeled cycle; the ledger is missing "
                "the in-person trips that would reset this clock, so restock timing is uncertain"
            )
        elif ratio >= 0.8:
            drivers.append(
                Driver("replenishment_due", min(1.2, 0.75 * ratio), f"due for restock: {cadence_note}")
            )
        elif ratio < 0.3:
            drivers.append(
                Driver("replenishment_due", -0.90, f"recently stocked: {cadence_note}")
            )
        else:
            drivers.append(
                Driver("replenishment_due", -0.25, f"mid-cycle: {cadence_note}")
            )
    elif item_profile:
        unknowns.append(f"no measurable repurchase cadence for '{item_profile.item}'")

    # --- quality fit ---------------------------------------------------------
    quality = preference.quality_importance.value
    if category_profile:
        quality = category_profile.quality_importance.value
    candidate_premium = sorted(PREMIUM_ATTRIBUTES.intersection(candidate.attributes))
    if quality is Importance.HIGH:
        if candidate_premium:
            drivers.append(
                Driver(
                    "quality_fit",
                    0.50,
                    f"carries {', '.join(candidate_premium)}; buyer pays up for quality here",
                )
            )
        else:
            drivers.append(
                Driver(
                    "quality_fit",
                    -0.35,
                    "no premium attribute, but the buyer usually buys premium in this category",
                )
            )
    elif quality is Importance.MEDIUM and candidate_premium:
        drivers.append(
            Driver("quality_fit", 0.25, f"carries {', '.join(candidate_premium)}")
        )

    # --- recurring vs one-off ------------------------------------------------
    if item_profile:
        if item_profile.repeat_behavior is RepeatBehavior.RECURRING:
            drivers.append(Driver("recurring_item", 0.25, "an established recurring purchase"))
        elif item_profile.repeat_behavior is RepeatBehavior.REPEAT:
            drivers.append(Driver("recurring_item", 0.10, "bought twice; a tentative repeat"))
        else:
            drivers.append(
                Driver("recurring_item", -0.35, "bought once; not an established habit")
            )

    # --- channel fit ---------------------------------------------------------
    if category_profile and category_profile.preferred_channel and channel:
        if channel == category_profile.preferred_channel:
            drivers.append(
                Driver(
                    "channel_fit",
                    0.30,
                    f"buyer sources '{category_profile.category}' from {channel}",
                )
            )
        else:
            drivers.append(
                Driver(
                    "channel_fit",
                    -0.25,
                    f"buyer usually sources '{category_profile.category}' from "
                    f"{category_profile.preferred_channel}, not {channel}",
                )
            )

    # --- negative feedback on the item --------------------------------------
    if item_profile and item_profile.negative_signals:
        penalty = 0.0
        for kind, count in item_profile.negative_signals.items():
            penalty += (0.6 if kind in ("RETURN", "CANCELLATION") else 0.3) * count
        penalty = min(penalty, 1.8)
        if penalty:
            detail = ", ".join(f"{k.lower()} x{v}" for k, v in item_profile.negative_signals.items())
            drivers.append(Driver("negative_feedback", -penalty, f"prior {detail}"))

    # --- unobservable attributes --------------------------------------------
    if candidate.condition is Condition.UNKNOWN:
        unknowns.append(
            "candidate condition is UNKNOWN and the history has no condition preference; "
            "this must not be treated as PASS by the Mandate Engine"
        )
    elif not preference.condition_preference.observable:
        unknowns.append(
            f"candidate is {candidate.condition.value}, but the history carries no "
            "condition preference to compare it against"
        )
    if candidate.delivery_days is not None and not preference.delivery_importance.observable:
        unknowns.append("delivery importance is unobservable in this history")
    if candidate.return_window_days is not None and not preference.returns_importance.observable:
        unknowns.append("return-policy importance is unobservable in this history")

    # --- combine -------------------------------------------------------------
    total = BASE_LOG_ODDS + sum(d.contribution for d in drivers)
    probability = _sigmoid(total)

    if item_profile:
        evidence = item_profile.evidence_weight
    elif category_profile:
        evidence = category_profile.evidence_weight * 0.5
    else:
        evidence = 0.0

    confidence = 1.0 - 0.5 ** (max(evidence, 0.0) / 3.0)
    if category_profile is None:
        confidence *= 0.40  # cross-category transfer from the general profile
    confidence *= max(0.40, 1.0 - 0.10 * len(unknowns))
    confidence = round(min(0.95, max(0.05, confidence)), 4)

    positives = sorted(
        (d for d in drivers if d.contribution > 0), key=lambda d: -d.contribution
    )
    negatives = sorted((d for d in drivers if d.contribution < 0), key=lambda d: d.contribution)

    return PurchasePrediction(
        probability=probability,
        confidence=confidence,
        positive_drivers=positives,
        negative_drivers=negatives,
        unknowns=unknowns,
        matched={
            "item_profile": item_profile.item if item_profile else None,
            "category_profile": category_key,
            "preference_scope": preference.category or "general",
            "price_reference": reference_label or None,
            "price_sensitivity_used": sensitivity.value,
            "transferred_from_general": category_profile is None,
        },
        profile_version=profile.version,
        base_rate=_sigmoid(BASE_LOG_ODDS),
    )
