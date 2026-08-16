"""End-to-end demo: profile -> prediction -> new transaction -> updated profile.

Run from the repository root:

    python3 buyer_history/examples/demo.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "buyer_history" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from buyer_history import (  # noqa: E402
    ActionType,
    CandidateRecord,
    Condition,
    Decision,
    EventStore,
    FeedbackEvent,
    FeedbackKind,
    NormalizedTransaction,
    Outcome,
    PredictionContext,
    PurchaseCandidate,
    ShoppingTrajectory,
    buyer_state_of,
    build_profile_from_workbook,
    export_bundle,
    predict_purchase_probability,
    update_profile,
)

# Defaults to the synthetic fixture so the demo runs on a fresh clone. Point it
# at a real workbook by passing a path:
#     python3 buyer_history/examples/demo.py "transaction data/…​.xlsx"
FIXTURE = ROOT / "buyer_history" / "fixtures" / "synthetic_household.xlsx"
WORKBOOK = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE
OUT_DIR = ROOT / "buyer_history" / "data"

# A fixed "today" keeps the demo deterministic and reproducible.
TODAY = date(2026, 8, 16)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def show_signal(label: str, signal) -> None:
    value = signal.value
    if hasattr(value, "value"):
        value = value.value
    print(f"  {label:<28} {str(value):<44} [{signal.source.value}/{signal.confidence_band.value}]")


def main() -> None:
    # ------------------------------------------------------------------
    rule("1. NORMALIZE  --  every channel into one common schema")
    # ------------------------------------------------------------------
    print(f"  source        {WORKBOOK.name}")
    bundle = build_profile_from_workbook(WORKBOOK, buyer_id="household", as_of=TODAY)

    by_channel: dict[str, int] = {}
    for txn in bundle.transactions:
        by_channel[txn.channel] = by_channel.get(txn.channel, 0) + 1
    orders = len({t.order_id for t in bundle.transactions})
    spend = sum(t.line_spend for t in bundle.transactions)

    print(f"  kept          {len(bundle.transactions)} line items across {orders} orders (${spend:,.2f})")
    print(f"  by channel    {by_channel}")
    print(f"  excluded      {len(bundle.excluded)} lines as noise")
    reasons: dict[str, int] = {}
    for row in bundle.excluded:
        reasons[row.rule] = reasons.get(row.rule, 0) + 1
    for code, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"                  {code:<24} {count}")
    print(f"  window        {min(t.purchased_on for t in bundle.transactions)} "
          f"-> {max(t.purchased_on for t in bundle.transactions)}  (as_of {bundle.as_of})")

    # ------------------------------------------------------------------
    rule("2. BUYER PREFERENCE PROFILE  --  general (PRD hierarchy level 4)")
    # ------------------------------------------------------------------
    general = bundle.general
    print(f"  buyer_id={general.buyer_id}  version={bundle.version}  "
          f"confidence={general.confidence:.2f}")
    for name, signal in general.signals().items():
        if name in ("observed_price_range", "repeat_behavior", "replenishment_cadence_days",
                    "channel_preference", "preferred_brands", "disliked_brands"):
            continue
        show_signal(name, signal)

    price = general.observed_price_range.value
    print(f"\n  observed unit-price band     ${price['p10']:.2f} - ${price['p90']:.2f} "
          f"(median ${price['median']:.2f}, max ${price['max']:.2f})")

    print("\n  preferred brands (2+ separate orders):")
    for entry in general.preferred_brands.value[:6]:
        print(f"    {entry['brand']:<22} {entry['occasions']} orders, "
              f"{entry['share']:.0%} of branded evidence")

    print("\n  channel preference:")
    for channel, info in general.channel_preference.value.items():
        print(f"    {channel:<22} {info['orders']} orders, {info['share']:.0%} of evidence")

    cadence = general.replenishment_cadence_days.value
    print(f"\n  replenishment: median {cadence['median_days']}d across "
          f"{cadence['items_with_cadence']} items")
    for entry in cadence["top_recurring"]:
        print(f"    {entry['item']:<22} every {entry['cadence_days']:>6.1f}d "
              f"({entry['cadence_source']}), next due {entry['next_due_on']}")

    print("\n  NOT OBSERVABLE in this history (must surface as UNKNOWN, never PASS):")
    for name in general.unknowns():
        print(f"    - {name}: {getattr(general, name).evidence[0][:96]}...")

    # ------------------------------------------------------------------
    rule("3. CATEGORY PROFILES  --  price sensitivity varies by category")
    # ------------------------------------------------------------------
    ranked = sorted(bundle.category_profiles.values(), key=lambda p: -p.evidence_weight)
    print(f"  {'category':<34} {'orders':>6} {'pen':>6} {'spend':>9} "
          f"{'sens':<7} {'quality':<7} {'conf':>5}")
    for profile in ranked[:10]:
        print(f"  {profile.category:<34} {profile.orders_with_category:>6} "
              f"{profile.penetration_household:>6.2f} ${profile.total_spend:>8.2f} "
              f"{profile.price_sensitivity.value.value:<7} "
              f"{profile.quality_importance.value.value:<7} {profile.confidence:>5.2f}")

    protein = bundle.category_profiles.get("Groceries > Protein")
    if protein:
        print(f"\n  why '{protein.category}' reads {protein.price_sensitivity.value.value}:")
        for line in protein.price_sensitivity.evidence:
            print(f"    - {line}")

    # ------------------------------------------------------------------
    rule("4. PREDICT  --  predict_purchase_probability(profile, candidate, context)")
    # ------------------------------------------------------------------
    context = PredictionContext(as_of=TODAY)
    candidates = [
        PurchaseCandidate(
            candidate_id="c1",
            item="Whole Bean Coffee",
            category="Groceries > Coffee",
            unit_price=16.49,
            brand="Lavazza",
            channel="Evermart",
        ),
        PurchaseCandidate(
            candidate_id="c2",
            item="Whole Bean Coffee",
            category="Groceries > Coffee",
            unit_price=64.99,
            brand="Subtle Earth",
            channel="Evermart",
            attributes=["organic", "bulk"],
        ),
        PurchaseCandidate(
            candidate_id="c3",
            item="Whey Protein",
            category="Groceries > Protein",
            unit_price=99.99,
            brand="Anthony's",
            channel="Evermart",
            attributes=["grass_fed", "no_additives"],
        ),
        PurchaseCandidate(
            candidate_id="c4",
            item="Kale",
            category="Produce > Greens & Herbs",
            unit_price=3.29,
            channel="FreshCart",
        ),
        PurchaseCandidate(
            candidate_id="c5",
            item="Noise Cancelling Headphones",
            category="Electronics > Audio",
            unit_price=348.00,
            brand="Sony",
            channel="Evermart",
            condition=Condition.REFURBISHED,
            delivery_days=2,
            return_window_days=30,
        ),
    ]

    predictions = {}
    for candidate in candidates:
        prediction = predict_purchase_probability(bundle, candidate, context)
        predictions[candidate.candidate_id] = prediction
        price_text = f"${candidate.unit_price:.2f}"
        print(f"\n  [{candidate.candidate_id}] {candidate.item} {price_text} "
              f"({candidate.brand or 'unbranded'}, {candidate.channel})")
        print("   " + prediction.explain().replace("\n", "\n   "))

    print("\n  Note on [c5]: no electronics history survives the household noise filter,")
    print("  so it is scored from the general profile and its confidence is transfer-discounted.")

    # ------------------------------------------------------------------
    rule("5. UPDATE  --  update_profile(existing, new_transactions, feedback)")
    # ------------------------------------------------------------------
    new_purchase = NormalizedTransaction(
        txn_id="Evermart:EM-1011:0",
        order_id="EM-1011",
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
        model_weight=1.0,
        source_sheet="live",
    )
    feedback = [
        FeedbackEvent(
            kind=FeedbackKind.PURCHASE,
            item="Whole Bean Coffee",
            category="Groceries > Coffee",
            brand="Lavazza",
            channel="Evermart",
            occurred_on=date(2026, 8, 14),
            detail="accepted the agent's recommendation at $16.49",
        ),
        FeedbackEvent(
            kind=FeedbackKind.RECOMMENDATION_REJECTED,
            item="Whole Bean Coffee",
            category="Groceries > Coffee",
            brand="Subtle Earth",
            channel="Evermart",
            occurred_on=date(2026, 8, 14),
            detail="rejected the $64.99 bulk bag as too expensive",
        ),
    ]

    updated = update_profile(bundle, [new_purchase], feedback, as_of=TODAY)
    revision = updated.revisions[-1]
    print(f"  version {bundle.version} -> {updated.version}   reason: {revision.reason}")
    print(f"  transactions {len(bundle.transactions)} -> {len(updated.transactions)}, "
          f"feedback {len(bundle.feedback)} -> {len(updated.feedback)}")
    print("  changes:")
    for change in revision.changes:
        print(f"    - {change}")

    coffee_before = bundle.item_profiles["Whole Bean Coffee"]
    coffee_after = updated.item_profiles["Whole Bean Coffee"]
    print(f"\n  Whole Bean Coffee: {coffee_before.occasions} -> {coffee_after.occasions} occasions, "
          f"cadence {coffee_before.cadence_days:.1f}d -> {coffee_after.cadence_days:.1f}d, "
          f"next due {coffee_before.next_due_on} -> {coffee_after.next_due_on}")

    print("\n  re-scoring the same two coffee candidates against the updated profile:")
    for candidate_id in ("c1", "c2"):
        candidate = next(c for c in candidates if c.candidate_id == candidate_id)
        before = predictions[candidate_id]
        after = predict_purchase_probability(updated, candidate, context)
        print(f"    [{candidate_id}] {candidate.item} ${candidate.unit_price:>6.2f}  "
              f"P(buy) {before.probability:.3f} -> {after.probability:.3f}   "
              f"(v{before.profile_version} -> v{after.profile_version})")
        driver = next(
            (d for d in after.negative_drivers if d.name in ("replenishment_due", "brand_fit")),
            None,
        )
        if driver:
            print(f"           because {driver.name}: {driver.explanation}")

    # ------------------------------------------------------------------
    rule("6. RL-READY TRAJECTORY  --  state -> intent -> candidates -> outcome -> reward")
    # ------------------------------------------------------------------
    store = EventStore(OUT_DIR / "events.jsonl")
    store.clear()

    coffee_candidates = [c for c in candidates if c.item == "Whole Bean Coffee"]
    records = [
        CandidateRecord(
            candidate=candidate,
            prediction=predictions[candidate.candidate_id],
            selected=candidate.candidate_id == "c1",
        )
        for candidate in coffee_candidates
    ]

    trajectory = ShoppingTrajectory(
        trajectory_id="traj-2026-08-14-coffee",
        buyer_id=bundle.buyer_id,
        occurred_on=date(2026, 8, 14),
        buyer_state=buyer_state_of(bundle, "Groceries > Coffee"),
        intent={"goal": "restock whole bean coffee", "stated_budget": 25.0},
        mandate_ref="mandate-demo-001",
        candidates=records,
        action={"type": ActionType.EXECUTE.value, "selected_candidate": "c1"},
        decision=Decision.APPROVE,
        constraint_results={"FINAL_PRICE": "PASS", "CATEGORY": "PASS", "CONDITION": "PASS"},
        outcome=Outcome(purchased=True, final_price=17.49, reference_price=coffee_before.unit_price.median),
        feedback=feedback,
    )
    logged = store.append(trajectory)

    print(f"  logged -> {store.path.relative_to(ROOT)}")
    print(f"  decision={logged.decision.value}  action={logged.action['type']}  "
          f"purchased={logged.outcome.purchased}")
    print("  reward components:")
    for name, value in logged.rewards.to_dict().items():
        if name in ("total", "hard_failures"):
            continue
        print(f"    {name:<36} {value:+.4f}")
    print(f"    {'hard_failures':<36} {logged.rewards.hard_failures or 'none'}")
    print(f"    {'TOTAL':<36} {logged.rewards.total:+.4f}")

    # A counter-example: the same mission executed after a BLOCK.
    violating = ShoppingTrajectory(
        trajectory_id="traj-2026-08-14-violation",
        buyer_id=bundle.buyer_id,
        occurred_on=date(2026, 8, 14),
        buyer_state=buyer_state_of(bundle, "Groceries > Coffee"),
        intent={"goal": "restock whole bean coffee", "stated_budget": 25.0},
        candidates=records,
        action={"type": ActionType.EXECUTE.value, "selected_candidate": "c2"},
        decision=Decision.BLOCK,
        constraint_results={"FINAL_PRICE": "FAIL"},
        outcome=Outcome(purchased=True, final_price=69.99, reference_price=coffee_before.unit_price.median),
    )
    store.append(violating)
    print(f"\n  counter-example (executed after BLOCK): total reward "
          f"{violating.rewards.total:+.2f}, hard failures {violating.rewards.hard_failures}")

    # ------------------------------------------------------------------
    rule("7. DELIVERABLES")
    # ------------------------------------------------------------------
    written = export_bundle(updated, OUT_DIR)
    for name, path in written.items():
        print(f"  {name:<26} {path.relative_to(ROOT)}")
    print(f"  {'rl_events':<26} {store.path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
