"""Profile construction and continuous learning.

`update_profile` re-derives every profile from the full ledger instead of
patching values in place. That keeps updates deterministic and reproducible --
(ledger, feedback, as_of) always maps to the same profile -- and it means new
evidence never has to be reconciled against a stale aggregate. Recency
weighting, not mutation, is what makes newer behaviour dominate.

No model is retrained. An update is a recount.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from buyer_history.infer import (
    DEFAULT_HALF_LIFE_DAYS,
    build_category_profiles,
    build_item_profiles,
    build_preference_profile,
)
from buyer_history.noise import NoiseFilter
from buyer_history.normalize import load_workbook_history
from buyer_history.schema import (
    BuyerPreferenceProfile,
    BuyerProfileBundle,
    ExcludedTransaction,
    FeedbackEvent,
    FeedbackKind,
    NormalizedTransaction,
    ProfileRevision,
)

# Categories below this evidence weight get no dedicated preference profile;
# callers fall back to the general profile rather than trusting a single line.
MIN_CATEGORY_EVIDENCE = 0.5


def _rebuild(
    buyer_id: str,
    transactions: Sequence[NormalizedTransaction],
    feedback: Sequence[FeedbackEvent],
    as_of: date,
    modeled_monthly_occasions: dict[tuple[str, str], float],
    modeled_category_occasions: dict[tuple[str, str], float],
    half_life_days: float,
) -> tuple[
    BuyerPreferenceProfile,
    dict[str, BuyerPreferenceProfile],
    dict,
    dict,
]:
    item_profiles = build_item_profiles(
        transactions,
        as_of=as_of,
        modeled_monthly_occasions=modeled_monthly_occasions,
        feedback=feedback,
        half_life_days=half_life_days,
    )
    category_profiles = build_category_profiles(
        transactions,
        as_of=as_of,
        modeled_category_occasions=modeled_category_occasions,
        half_life_days=half_life_days,
    )

    general = build_preference_profile(
        buyer_id=buyer_id,
        rows=transactions,
        as_of=as_of,
        item_profiles=item_profiles,
        category=None,
        feedback=feedback,
        half_life_days=half_life_days,
    )

    per_category: dict[str, BuyerPreferenceProfile] = {}
    for category, profile in category_profiles.items():
        if profile.evidence_weight < MIN_CATEGORY_EVIDENCE:
            continue
        rows = [t for t in transactions if t.category == category]
        per_category[category] = build_preference_profile(
            buyer_id=buyer_id,
            rows=rows,
            as_of=as_of,
            item_profiles=item_profiles,
            category=category,
            feedback=[f for f in feedback if f.category in (None, category)],
            half_life_days=half_life_days,
        )

    return general, per_category, category_profiles, item_profiles


def build_profile(
    transactions: Sequence[NormalizedTransaction],
    buyer_id: str = "household",
    as_of: date | None = None,
    feedback: Sequence[FeedbackEvent] = (),
    excluded: Sequence[ExcludedTransaction] = (),
    modeled_monthly_occasions: dict[tuple[str, str], float] | None = None,
    modeled_category_occasions: dict[tuple[str, str], float] | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> BuyerProfileBundle:
    """Build version 1 of a buyer's profile bundle from normalized transactions."""
    transactions = sorted(transactions, key=lambda t: (t.purchased_on, t.order_id, t.item))
    if not transactions:
        raise ValueError("cannot build a profile from an empty transaction ledger")

    as_of = as_of or max(t.purchased_on for t in transactions)
    modeled_monthly_occasions = modeled_monthly_occasions or {}
    modeled_category_occasions = modeled_category_occasions or {}

    general, per_category, category_profiles, item_profiles = _rebuild(
        buyer_id,
        transactions,
        feedback,
        as_of,
        modeled_monthly_occasions,
        modeled_category_occasions,
        half_life_days,
    )

    return BuyerProfileBundle(
        buyer_id=buyer_id,
        version=1,
        as_of=as_of,
        general=general,
        categories=per_category,
        category_profiles=category_profiles,
        item_profiles=item_profiles,
        transactions=list(transactions),
        feedback=list(feedback),
        excluded=list(excluded),
        modeled_monthly_occasions=dict(modeled_monthly_occasions),
        modeled_category_occasions=dict(modeled_category_occasions),
        revisions=[
            ProfileRevision(
                version=1,
                created_on=as_of,
                reason="initial build from transaction history",
                transactions_added=len(transactions),
                feedback_applied=len(feedback),
                changes=[
                    f"{len(item_profiles)} item profile(s)",
                    f"{len(category_profiles)} category profile(s)",
                    f"{len(per_category)} category preference profile(s)",
                    f"{len(excluded)} excluded line(s) retained for audit",
                ],
            )
        ],
    )


def build_profile_from_workbook(
    path: str | Path,
    buyer_id: str = "household",
    as_of: date | None = None,
    noise_filter: NoiseFilter | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    transaction_sheets: Sequence[tuple[str, str]] | None = None,
) -> BuyerProfileBundle:
    """Load a MandateLab workbook and build the initial profile bundle."""
    history = load_workbook_history(
        path, noise_filter=noise_filter, transaction_sheets=transaction_sheets
    )
    return build_profile(
        transactions=history.transactions,
        buyer_id=buyer_id,
        as_of=as_of,
        excluded=history.excluded,
        modeled_monthly_occasions=history.modeled_monthly_occasions,
        modeled_category_occasions=history.modeled_category_occasions,
        half_life_days=half_life_days,
    )


def _describe_changes(
    old: BuyerProfileBundle,
    new_general: BuyerPreferenceProfile,
    new_categories: dict[str, BuyerPreferenceProfile],
    new_item_profiles: dict,
    new_category_profiles: dict,
) -> list[str]:
    changes: list[str] = []

    old_value = old.general.price_sensitivity.value
    new_value = new_general.price_sensitivity.value
    if old_value != new_value:
        changes.append(f"general price_sensitivity {old_value} -> {new_value}")

    old_quality = old.general.quality_importance.value
    new_quality = new_general.quality_importance.value
    if old_quality != new_quality:
        changes.append(f"general quality_importance {old_quality} -> {new_quality}")

    added_items = sorted(set(new_item_profiles) - set(old.item_profiles))
    for item in added_items:
        changes.append(f"new item profile: {item}")

    for item, profile in new_item_profiles.items():
        previous = old.item_profiles.get(item)
        if previous and previous.repeat_behavior != profile.repeat_behavior:
            changes.append(
                f"{item}: {previous.repeat_behavior.value} -> {profile.repeat_behavior.value} "
                f"({previous.occasions} -> {profile.occasions} occasions)"
            )
        elif previous and previous.occasions != profile.occasions:
            changes.append(
                f"{item}: occasions {previous.occasions} -> {profile.occasions}"
            )

    added_categories = sorted(set(new_category_profiles) - set(old.category_profiles))
    for category in added_categories:
        changes.append(f"new category profile: {category}")

    for category, profile in new_categories.items():
        previous = old.categories.get(category)
        if previous and previous.price_sensitivity.value != profile.price_sensitivity.value:
            changes.append(
                f"{category}: price_sensitivity "
                f"{previous.price_sensitivity.value} -> {profile.price_sensitivity.value}"
            )

    old_disliked = {
        entry.get("brand") for entry in (old.general.disliked_brands.value or []) if isinstance(entry, dict)
    }
    new_disliked = {
        entry.get("brand") for entry in (new_general.disliked_brands.value or []) if isinstance(entry, dict)
    }
    for brand in sorted(new_disliked - old_disliked):
        changes.append(f"brand flagged from negative feedback: {brand}")

    return changes or ["no material change to inferred preferences"]


def update_profile(
    existing_profile: BuyerProfileBundle,
    new_transactions: Sequence[NormalizedTransaction] = (),
    feedback: Sequence[FeedbackEvent] | None = None,
    as_of: date | None = None,
    noise_filter: NoiseFilter | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> BuyerProfileBundle:
    """Fold new transactions and feedback into a new, versioned profile.

    Returns a new bundle; `existing_profile` is left untouched so a caller can
    diff versions or roll back.
    """
    noise_filter = noise_filter or NoiseFilter()
    feedback = list(feedback or [])

    kept, dropped = noise_filter.split(new_transactions)

    known_ids = {t.txn_id for t in existing_profile.transactions}
    fresh = [t for t in kept if t.txn_id not in known_ids]

    ledger = sorted(
        [*existing_profile.transactions, *fresh],
        key=lambda t: (t.purchased_on, t.order_id, t.item),
    )
    all_feedback = [*existing_profile.feedback, *feedback]

    if as_of is None:
        candidates = [t.purchased_on for t in ledger]
        candidates.extend(f.occurred_on for f in all_feedback if f.occurred_on)
        candidates.append(existing_profile.as_of)
        as_of = max(candidates)

    general, per_category, category_profiles, item_profiles = _rebuild(
        existing_profile.buyer_id,
        ledger,
        all_feedback,
        as_of,
        existing_profile.modeled_monthly_occasions,
        existing_profile.modeled_category_occasions,
        half_life_days,
    )

    changes = _describe_changes(
        existing_profile, general, per_category, item_profiles, category_profiles
    )
    if dropped:
        changes.append(f"{len(dropped)} new line(s) filtered as noise")

    reasons: list[str] = []
    if fresh:
        reasons.append(f"{len(fresh)} new transaction(s)")
    if feedback:
        kinds = sorted({f.kind.value for f in feedback})
        reasons.append(f"feedback: {', '.join(kinds)}")
    reason = "; ".join(reasons) or "recomputed with no new evidence"

    revision = ProfileRevision(
        version=existing_profile.version + 1,
        created_on=as_of,
        reason=reason,
        transactions_added=len(fresh),
        feedback_applied=len(feedback),
        changes=changes,
    )

    return BuyerProfileBundle(
        buyer_id=existing_profile.buyer_id,
        version=existing_profile.version + 1,
        as_of=as_of,
        general=general,
        categories=per_category,
        category_profiles=category_profiles,
        item_profiles=item_profiles,
        transactions=ledger,
        feedback=all_feedback,
        excluded=[*existing_profile.excluded, *dropped],
        modeled_monthly_occasions=dict(existing_profile.modeled_monthly_occasions),
        modeled_category_occasions=dict(existing_profile.modeled_category_occasions),
        revisions=[*existing_profile.revisions, revision],
    )


def record_purchase(
    bundle: BuyerProfileBundle,
    transaction: NormalizedTransaction,
    as_of: date | None = None,
) -> BuyerProfileBundle:
    """Convenience wrapper: one completed purchase becomes one profile version."""
    return update_profile(
        bundle,
        [transaction],
        [
            FeedbackEvent(
                kind=FeedbackKind.PURCHASE,
                item=transaction.item,
                category=transaction.category,
                brand=transaction.brand,
                channel=transaction.channel,
                occurred_on=transaction.purchased_on,
                detail=f"purchased at ${transaction.unit_price:.2f}",
            )
        ],
        as_of=as_of,
    )
