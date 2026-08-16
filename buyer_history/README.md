# buyer_history — Existing Buyer Preference Learning

MandateLab PRD §5.2. Infers a `BuyerPreferenceProfile` from real purchase
behaviour, predicts purchase likelihood with an explainable model, and updates
the profile as new transactions and feedback arrive.

Stdlib only — no pandas, no openpyxl, no network. Python ≥ 3.11.

```bash
python3 buyer_history/examples/demo.py       # profile → prediction → update → trajectory
python3 buyer_history/tests/test_buyer_history.py
```

Both run on the synthetic fixture and need nothing else on a fresh clone.

## Data

**Nothing in this repo contains real purchase history.** The demo and tests use
`fixtures/synthetic_household.xlsx` — an invented buyer, invented orders, dates
and prices. Real household data lives in a gitignored `transaction data/`
directory, and the profiles derived from it are gitignored too.

```bash
# regenerate the fixture (deterministic)
python3 buyer_history/fixtures/make_synthetic_workbook.py

# run against a real workbook instead
python3 buyer_history/examples/demo.py "transaction data/<file>.xlsx"
```

Transaction sheets are discovered by the `<Channel>_Clean` naming convention, so
both workbooks load through the same call with no configuration.

The fixture is built to exercise every branch that matters: two channels with
different column layouts, recurring and one-off items, a category where the
buyer absorbs a price rise and one where they retreat from a spike, branded
goods alongside unbranded produce, a modeled cadence that outruns the recorded
order dates, and one noise row per exclusion rule.

## Two invariants

1. **History is evidence, not ground truth.** Every value carries `source`,
   `confidence` and `evidence`. Current explicit intent outranks anything here.
2. **Behaviour never produces a hard mandate.** `to_mandate_hints()` returns
   `hard_constraints: []` by construction. Constraints and enforcement belong to
   the Mandate Engine.

## Public API

```python
build_profile_from_workbook(path, buyer_id, as_of) -> BuyerProfileBundle
build_profile(transactions, ...)                   -> BuyerProfileBundle
predict_purchase_probability(profile, candidate, context) -> PurchasePrediction
update_profile(existing_profile, new_transactions, feedback=None) -> BuyerProfileBundle
export_bundle(bundle, out_dir) -> dict[str, Path]
```

`BuyerProfileBundle` holds the general profile, per-category profiles, item
profiles, the transaction ledger and a revision history.

## What the source data supports

Findings below come from the real household workbook (133 clean line items, 26
orders, $1,502.62, plus 41 noise lines). The fixture reproduces the same
structure at smaller scale — 63 lines, 18 orders, 6 noise lines — including the
per-category sensitivity split described next.

**Observed** — category affinity, item repeat counts, unit-price ranges,
replenishment cadence, channel/merchant preference, brand shares, recurring vs
one-off classification.

**Inferred** (stated heuristics, confidence attached) — price sensitivity and
quality importance, both **per category**. A single global price-sensitivity
number would be wrong for this buyer: they repurchased whey protein through an
$89.99 → $99.99 rise without downtrading (LOW), but stepped back from a $69.99
coffee bag to ~$15–18 (HIGH). The fixture encodes the same contrast at
$84.99 → $94.99 and $64.99 → $14.99.

**Not observable — returned as `UNKNOWN` with `observable=False`:**

| Field | Why |
|---|---|
| `condition_preference` | No line states new/used/refurbished. It is all groceries. |
| `returns_importance` | Zero returns or cancellations in the ledger. |
| `delivery_importance` | No delivery attribute exists in the source. |

This distinction is deliberate. PRD §10 requires that uncertain hard-constraint
data does not silently pass, so "unobservable" must be distinguishable from
"observed and neutral". `predict_purchase_probability` surfaces these in
`prediction.unknowns` rather than scoring them.

**Electronics has no category profile.** Every electronics row in the source was
excluded as a one-off durable, so a headphones candidate is scored from the
general profile (PRD §5.2 hierarchy level 4) with transfer-discounted
confidence, and `matched.transferred_from_general` is set. Pass
`NoiseFilter(exclude_durables=False)` to retain durables when a mission needs
them.

## How the numbers are produced

Every line is weighted by `model_weight × 0.5^(age_days / 270)` — the
workbook's own signal-reliability figure times a recency half-life.

**Price sensitivity** (0–1, higher = more sensitive), bucketed at 0.40 / 0.62:

```
0.40 × (1 − price-move tolerance)      # do they keep buying as price rises?
0.35 × within-item price dispersion    # measured per item, not across the category
0.25 × (1 − premium-attribute rate)    # organic, grass-fed, cage-free, wild-caught…
```

**Quality importance** = `0.6 × premium rate + 0.4 × brand loyalty`, bucketed at
0.25 / 0.55.

**Cadence** prefers the workbook's rescaled `Modeled Current Monthly Occasions`
over raw order gaps, because the README states the household now shops H Mart
~2×/week and the sparse Weee! dates understate it. Which was used is recorded in
`cadence_source`.

**Prediction** is additive in log-odds: a base rate plus named signed drivers
(`item_affinity`, `category_affinity`, `price_fit`, `brand_fit`,
`replenishment_due`, `quality_fit`, `recurring_item`, `channel_fit`,
`negative_feedback`, and `explicit_intent:*`). No fitted weight vector, so
`prediction.explain()` prints the full reasoning. Probability and confidence are
separate: a candidate can suit the buyer well while the evidence behind that
judgement is thin.

## Continuous learning

`update_profile` re-derives every profile from the full ledger rather than
patching aggregates, so `(ledger, feedback, as_of)` always maps to the same
profile. Recency weighting — not mutation — is what makes new behaviour
dominate. Duplicate `txn_id`s are ignored; the input bundle is never mutated;
each call appends a `ProfileRevision` describing what changed. No model is
retrained — an update is a recount.

Feedback kinds: `PURCHASE`, `RETURN`, `CANCELLATION`,
`RECOMMENDATION_ACCEPTED`, `RECOMMENDATION_REJECTED`, `EXPLICIT_PREFERENCE`.
Returns and rejections feed `disliked_brands` and per-item negative signals.
Explicit preferences are recorded for provenance but applied per-mission through
`PredictionContext.explicit_preferences`, since current intent is a property of
the request, not a stored trait.

## RL-ready logging

`ShoppingTrajectory` records
`buyer_state → intent → candidates → action → decision → outcome → feedback → rewards`
as JSONL via `EventStore`. `compute_rewards` scores the PRD §7 dimensions
deterministically, so a log can be replayed and rescored offline. Hard failures
(`EXECUTION_AFTER_BLOCK`, `EXECUTION_AFTER_UNRESOLVED_REVIEW`,
`HARD_MANDATE_VIOLATION:*`) each carry −5.0. Nothing is trained here.

## Deliverables

`export_bundle()` writes to `buyer_history/data/` (gitignored, since output
derived from real data carries the same detail as the input):

| File | Contents |
|---|---|
| `normalized_transactions.json` | every line in the common schema |
| `excluded_transactions.json` | noise lines with rule + reason |
| `buyer_profile.json` | general + per-category `BuyerPreferenceProfile`, revisions |
| `category_profiles.json` | one profile per category |
| `item_profiles.json` | one profile per item |
| `mandate_hints.json` | soft preferences for the Mandate Engine |
| `events.jsonl` | RL-ready trajectories |

On the fixture that's 15 category and 25 item profiles; on the real workbook,
22 and 68.

## Known limitations

- **The H Mart blind spot.** The household shops H Mart ~2×/week but those
  receipts were never captured, so "days since last purchase" is unreliable for
  Weee!-proxied items. Where a gap exceeds 3× the modeled cycle, the restock
  bonus is damped and an explicit unknown is emitted rather than reporting the
  item as long overdue.
- **Category keys follow the source taxonomy.** `Groceries > Meat & Poultry`
  (Amazon) and `Meat & Poultry` (Weee!) stay separate rather than being merged
  by an invented mapping. `resolve_category_key` falls back exact → leaf → top.
- **Brand extraction is a lexicon.** Deterministic and auditable over this
  fixture; a new supplier needs a lexicon entry or it resolves to `None`.
- **Channel share is line-weighted**, so Weee! (108 lines / 10 orders) leads
  Amazon (25 lines / 16 orders). Order counts are reported alongside.
