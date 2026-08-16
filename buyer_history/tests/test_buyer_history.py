"""Sanity checks. Runs standalone (no pytest needed):

    python3 buyer_history/tests/test_buyer_history.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "buyer_history" / "src"))

from buyer_history import (  # noqa: E402
    Condition,
    FeedbackEvent,
    FeedbackKind,
    Importance,
    NoiseFilter,
    NormalizedTransaction,
    PredictionContext,
    PurchaseCandidate,
    Source,
    build_profile_from_workbook,
    extract_attributes,
    extract_brand,
    predict_purchase_probability,
    update_profile,
)

WORKBOOK = ROOT / "buyer_history" / "fixtures" / "synthetic_household.xlsx"
TODAY = date(2026, 8, 16)

_checks = 0


def check(condition: bool, label: str) -> None:
    global _checks
    _checks += 1
    if not condition:
        raise AssertionError(label)
    print(f"  ok  {label}")


def build():
    return build_profile_from_workbook(WORKBOOK, buyer_id="synthetic_household", as_of=TODAY)


def test_normalization() -> None:
    print("\nnormalization")
    bundle = build()
    check(len(bundle.transactions) == 63, "63 clean line items loaded")
    check(
        {t.channel for t in bundle.transactions} == {"Evermart", "FreshCart"},
        "both channels present",
    )
    check(all(t.unit_price > 0 for t in bundle.transactions), "every line has a unit price")
    check(
        all(t.category and t.channel for t in bundle.transactions),
        "channel and category preserved on every line",
    )
    check(
        extract_brand("Amazon Basics Soft and Strong 2-Ply Toilet Paper") == "Amazon Basics",
        "brand parsed from raw item text",
    )
    check(extract_brand("Green Curly Kale, 1 bunch") is None, "commodity produce has no brand")
    check(
        "grass_fed" in extract_attributes("Raw Grass Fed Whey Protein Powder, Unflavored"),
        "quality attributes parsed",
    )


def test_noise_filter() -> None:
    print("\nnoise filter")
    noise = NoiseFilter()
    check(
        noise.classify("Prime Student Fee - monthly membership", "Digital Subscription") is not None,
        "subscriptions excluded",
    )
    check(
        noise.classify("Ninja Nutri-Blender Pro with Auto-iQ", "Kitchen") is not None,
        "one-off durables excluded",
    )
    check(
        noise.classify("Cascade Complete Gel All-in-1 Dishwasher Detergent", "Household > Cleaning")
        is None,
        "recurring household consumables kept",
    )
    check(
        noise.classify("Solgar Vitamin B12 1000 mcg", "Health > Supplements") is None,
        "supplements kept while episodic medical items are dropped",
    )
    check(
        NoiseFilter(exclude_durables=False).classify("Logitech MX Keys Mini", "Electronics & Tech")
        is None,
        "durables retained when a durable-category mission needs them",
    )


def test_unobservable_stays_unknown() -> None:
    print("\nunobservable attributes")
    bundle = build()
    general = bundle.general
    for name in ("condition_preference", "delivery_importance", "returns_importance"):
        signal = getattr(general, name)
        check(signal.value is Importance.UNKNOWN, f"{name} is UNKNOWN")
        check(not signal.observable, f"{name} marked unobservable")
        check(signal.confidence == 0.0, f"{name} carries zero confidence")
    check("condition_preference" in general.unknowns(), "unknowns() lists condition")
    check(
        general.to_mandate_hints()["hard_constraints"] == [],
        "behaviour never emits a hard constraint",
    )


def test_price_sensitivity_is_category_specific() -> None:
    print("\ncategory-specific price sensitivity")
    bundle = build()
    protein = bundle.category_profiles["Groceries > Protein"]
    coffee = bundle.category_profiles["Groceries > Coffee"]
    check(
        protein.price_sensitivity.value is Importance.LOW,
        "protein reads LOW (repurchased through a 12% price rise)",
    )
    check(
        coffee.price_sensitivity.value is Importance.HIGH,
        "coffee reads HIGH (stepped back down from the $64.99 bag)",
    )
    check(
        protein.price_sensitivity.source is Source.INFERRED,
        "price sensitivity is marked INFERRED, not OBSERVED",
    )


def test_prediction_is_deterministic_and_explained() -> None:
    print("\nprediction")
    bundle = build()
    context = PredictionContext(as_of=TODAY)
    cheap = PurchaseCandidate(
        candidate_id="a",
        item="Whole Bean Coffee",
        category="Groceries > Coffee",
        unit_price=16.49,
        brand="Lavazza",
        channel="Evermart",
    )
    dear = PurchaseCandidate(
        candidate_id="b",
        item="Whole Bean Coffee",
        category="Groceries > Coffee",
        unit_price=64.99,
        brand="Subtle Earth",
        channel="Evermart",
    )
    first = predict_purchase_probability(bundle, cheap, context)
    second = predict_purchase_probability(bundle, cheap, context)
    check(first.probability == second.probability, "same inputs give the same probability")
    check(
        first.probability > predict_purchase_probability(bundle, dear, context).probability,
        "the in-band price outranks the far-above-band price",
    )
    check(bool(first.positive_drivers), "positive drivers returned")
    check(
        any("condition" in u for u in first.unknowns),
        "unknown condition is surfaced rather than silently passed",
    )

    unseen = PurchaseCandidate(
        candidate_id="c",
        item="Noise Cancelling Headphones",
        category="Electronics > Audio",
        unit_price=348.00,
        brand="Sony",
        condition=Condition.REFURBISHED,
    )
    transferred = predict_purchase_probability(bundle, unseen, context)
    check(transferred.matched["transferred_from_general"], "unseen category falls back to general")
    check(
        transferred.confidence < first.confidence,
        "cross-category transfer is confidence-discounted",
    )


def test_update_is_versioned() -> None:
    print("\ncontinuous learning")
    bundle = build()
    purchase = NormalizedTransaction(
        txn_id="Evermart:test-order:0",
        order_id="test-order",
        purchased_on=date(2026, 8, 14),
        channel="Evermart",
        merchant="Evermart Retail",
        item="Whole Bean Coffee",
        category="Groceries > Coffee",
        quantity=1,
        unit_price=16.49,
        line_spend=16.49,
        raw_item="Lavazza Espresso Whole Bean Coffee, Medium Roast, 2.2 lb Bag",
        brand="Lavazza",
    )
    rejection = FeedbackEvent(
        kind=FeedbackKind.RECOMMENDATION_REJECTED,
        item="Whole Bean Coffee",
        category="Groceries > Coffee",
        brand="Subtle Earth",
        occurred_on=date(2026, 8, 14),
    )
    updated = update_profile(bundle, [purchase], [rejection], as_of=TODAY)

    check(updated.version == bundle.version + 1, "version incremented")
    check(bundle.version == 1, "the original bundle is left untouched")
    check(len(updated.transactions) == len(bundle.transactions) + 1, "ledger grew by one")
    check(
        updated.item_profiles["Whole Bean Coffee"].occasions
        == bundle.item_profiles["Whole Bean Coffee"].occasions + 1,
        "item occasions updated",
    )
    disliked = {e["brand"] for e in updated.general.disliked_brands.value}
    check("Subtle Earth" in disliked, "rejected brand recorded as a negative signal")
    check(bool(updated.revisions[-1].changes), "revision records what changed")

    again = update_profile(bundle, [purchase], [rejection], as_of=TODAY)
    check(
        again.general.price_sensitivity.value == updated.general.price_sensitivity.value,
        "rebuilds are deterministic",
    )
    # Re-applying the same transaction must not double count it.
    twice = update_profile(updated, [purchase], as_of=TODAY)
    check(
        len(twice.transactions) == len(updated.transactions),
        "duplicate transaction ids are ignored",
    )


def main() -> None:
    for test in (
        test_normalization,
        test_noise_filter,
        test_unobservable_stays_unknown,
        test_price_sensitivity_is_category_specific,
        test_prediction_is_deterministic_and_explained,
        test_update_is_versioned,
    ):
        test()
    print(f"\n{_checks} checks passed")


if __name__ == "__main__":
    main()
