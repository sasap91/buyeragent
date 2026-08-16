"""Adapter onto the shared `mandatelab_contracts.BuyerPreferenceProfile`.

Kept in its own module because it is the only part of `buyer_history` that needs
Pydantic. Import it when you want the shared contract; the rest of the package
stays dependency-free.

`PurchaseHistoryProfileBuilder` implements the `PreferenceProfileBuilder`
protocol, so a history-derived profile is interchangeable with a cold-start one
everywhere downstream.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from buyer_history.schema import (
    BuyerPreferenceProfile as InternalProfile,
    BuyerProfileBundle,
    Importance,
    PreferenceSignal as InternalSignal,
    Source,
)

if TYPE_CHECKING:  # pragma: no cover
    from mandatelab_contracts import BuyerPreferenceProfile as ContractProfile

# Category value used for the buyer-wide profile. The shared contract requires a
# non-empty category, but PRD section 5.2 puts general preferences one rung below
# category preferences, and `PreferenceSource.GENERAL_HISTORY` exists to label
# them -- so the scope is carried by the source, and this is its category name.
GENERAL_CATEGORY = "*"

# Bucket midpoints, used only when a signal carries no continuous score.
_FALLBACK_WEIGHT = {
    Importance.LOW: Decimal("0.25"),
    Importance.MEDIUM: Decimal("0.55"),
    Importance.HIGH: Decimal("0.85"),
    Importance.UNKNOWN: Decimal("0"),
}


def _unit(value: float | None) -> Decimal:
    """Clamp to the contract's 0..1 Decimal range."""
    if value is None:
        return Decimal("0")
    return Decimal(str(round(min(1.0, max(0.0, float(value))), 4)))


def _source_for(profile: InternalProfile, signal: InternalSignal):
    from mandatelab_contracts import PreferenceSource

    if not signal.observable or signal.source is Source.DEFAULT:
        return PreferenceSource.DEFAULT
    if signal.source is Source.EXPLICIT:
        return PreferenceSource.CURRENT_EXPLICIT
    if profile.category is None:
        return PreferenceSource.GENERAL_HISTORY
    return PreferenceSource.CATEGORY_HISTORY


def _importance(profile: InternalProfile, signal: InternalSignal):
    """Map an internal bucketed signal onto the shared PreferenceSignal."""
    from mandatelab_contracts import ImportanceLevel, PreferenceSignal

    value = signal.value if isinstance(signal.value, Importance) else Importance.UNKNOWN
    level = ImportanceLevel(value.value)
    weight = (
        _unit(signal.numeric_weight)
        if signal.numeric_weight is not None
        else _FALLBACK_WEIGHT[value]
    )
    return PreferenceSignal[ImportanceLevel](
        value=level,
        numeric_weight=weight,
        source=_source_for(profile, signal),
        confidence=_unit(signal.confidence),
    )


def _brands(profile: InternalProfile, signal: InternalSignal, key: str):
    from mandatelab_contracts import PreferenceSignal

    entries = signal.value or []
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        brand = entry.get("brand")
        if not brand:
            continue
        weight = entry.get("share") if key == "share" else 1.0
        out.append(
            PreferenceSignal[str](
                value=brand,
                numeric_weight=_unit(weight),
                source=_source_for(profile, signal),
                confidence=_unit(signal.confidence),
            )
        )
    return out


def to_contract_profile(
    bundle: BuyerProfileBundle,
    category: str | None = None,
) -> "ContractProfile":
    """Emit the shared BuyerPreferenceProfile for one category, or buyer-wide.

    Unobservable attributes are emitted as `ImportanceLevel.UNKNOWN` with
    confidence 0, never as a guessed level -- PRD section 10 requires that
    uncertain data cannot silently pass.

    `hard_rule_candidates` is always empty: this module learns from behaviour,
    and behaviour is evidence rather than a mandate. Only the cold-start path
    proposes candidate hard rules.
    """
    from mandatelab_contracts import BuyerPreferenceProfile

    profile = bundle.profile_for(category)

    return BuyerPreferenceProfile(
        buyer_id=bundle.buyer_id,
        category=profile.category or GENERAL_CATEGORY,
        price_sensitivity=_importance(profile, profile.price_sensitivity),
        quality_importance=_importance(profile, profile.quality_importance),
        delivery_importance=_importance(profile, profile.delivery_importance),
        return_policy_importance=_importance(profile, profile.returns_importance),
        # Nothing in a transaction ledger measures merchant trust: the buyer's
        # channel mix reflects assortment and habit, not a trust judgement.
        merchant_trust_importance=_importance(
            profile,
            InternalSignal(
                value=Importance.UNKNOWN,
                source=Source.DEFAULT,
                confidence=0.0,
                observable=False,
                evidence=["merchant trust is not measurable from purchase history"],
            ),
        ),
        preferred_brands=_brands(profile, profile.preferred_brands, "share"),
        disliked_brands=_brands(profile, profile.disliked_brands, "flat"),
        # Condition is unobservable in this history, and an empty list is the
        # contract's only way to say "no condition preference asserted".
        condition_preferences=[],
        hard_rule_candidates=[],
        created_at=datetime.combine(bundle.as_of, time.min, tzinfo=UTC),
    )


def all_contract_profiles(bundle: BuyerProfileBundle) -> dict[str, "ContractProfile"]:
    """Every category profile plus the buyer-wide one, keyed by category."""
    profiles = {GENERAL_CATEGORY: to_contract_profile(bundle, None)}
    for category in bundle.categories:
        profiles[category] = to_contract_profile(bundle, category)
    return profiles


class PurchaseHistoryProfileBuilder:
    """`PreferenceProfileBuilder` bound to purchase-history input (PRD 5.2).

        builder = PurchaseHistoryProfileBuilder(category="Groceries > Coffee")
        profile = builder.build_profile(bundle)
    """

    def __init__(self, category: str | None = None) -> None:
        self.category = category

    def build_profile(self, source: BuyerProfileBundle, /) -> "ContractProfile":
        return to_contract_profile(source, self.category)
