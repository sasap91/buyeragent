"""Shared data contracts for the Existing Buyer Preference Learning module.

Two rules from the PRD shape everything here:

1. Transaction history is *evidence*, not ground truth. Every inferred value
   carries its source, its confidence and the evidence behind it, so the Mandate
   Engine can decide how much weight to give it.
2. Behaviour never produces a hard mandate. Nothing in this module emits a MUST
   or MUST NOT -- only soft preferences that a mandate may consult.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, asdict
from datetime import date
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class Source(str, Enum):
    """Where a preference value came from, per PRD section 6."""

    OBSERVED = "OBSERVED"  # directly counted in the transaction ledger
    INFERRED = "INFERRED"  # derived from observed data by a stated heuristic
    TRANSFERRED = "TRANSFERRED"  # borrowed from the general profile, cross-category
    DEFAULT = "DEFAULT"  # no evidence at all; a stated fallback
    EXPLICIT = "EXPLICIT"  # stated by the buyer; outranks everything above


class Importance(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ConfidenceBand(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RepeatBehavior(str, Enum):
    RECURRING = "RECURRING"  # 3+ separate purchase occasions
    REPEAT = "REPEAT"  # exactly 2
    ONE_OFF = "ONE_OFF"  # exactly 1
    UNKNOWN = "UNKNOWN"


class Condition(str, Enum):
    NEW = "NEW"
    USED = "USED"
    REFURBISHED = "REFURBISHED"
    UNKNOWN = "UNKNOWN"


class CadenceSource(str, Enum):
    OBSERVED_GAPS = "OBSERVED_GAPS"  # mean gap between real purchase dates
    MODELED_CURRENT = "MODELED_CURRENT"  # workbook's rescaled current cadence
    NONE = "NONE"


class FeedbackKind(str, Enum):
    PURCHASE = "PURCHASE"
    RETURN = "RETURN"
    CANCELLATION = "CANCELLATION"
    RECOMMENDATION_ACCEPTED = "RECOMMENDATION_ACCEPTED"
    RECOMMENDATION_REJECTED = "RECOMMENDATION_REJECTED"
    EXPLICIT_PREFERENCE = "EXPLICIT_PREFERENCE"


def band_for(confidence: float) -> ConfidenceBand:
    if confidence <= 0.0:
        return ConfidenceBand.NONE
    if confidence < 0.34:
        return ConfidenceBand.LOW
    if confidence < 0.67:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.HIGH


# --------------------------------------------------------------------------
# Preference signal
# --------------------------------------------------------------------------


@dataclass
class PreferenceSignal:
    """One preference value plus its provenance.

    `observable` is False when the underlying attribute simply cannot be seen in
    the source data (product condition in a grocery history, for example). That
    is materially different from "seen and found to be neutral", and the Mandate
    Engine must be able to tell the two apart -- an unobservable attribute has to
    surface as UNKNOWN rather than silently pass.
    """

    value: Any
    source: Source
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    observable: bool = True
    # Continuous intensity behind a bucketed value, where one exists. Kept
    # alongside the bucket so the shared contract's `numeric_weight` can be
    # filled from the real score instead of a bucket midpoint.
    numeric_weight: float | None = None

    @property
    def confidence_band(self) -> ConfidenceBand:
        return band_for(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": jsonify(self.value),
            "source": self.source.value,
            "confidence": round(self.confidence, 4),
            "confidence_band": self.confidence_band.value,
            "observable": self.observable,
            "numeric_weight": (
                None if self.numeric_weight is None else round(self.numeric_weight, 4)
            ),
            "evidence": list(self.evidence),
        }


def unknown_signal(reason: str) -> PreferenceSignal:
    """A signal for something the source data cannot speak to."""
    return PreferenceSignal(
        value=Importance.UNKNOWN,
        source=Source.DEFAULT,
        confidence=0.0,
        evidence=[reason],
        observable=False,
    )


# --------------------------------------------------------------------------
# Normalized transactions
# --------------------------------------------------------------------------


@dataclass
class NormalizedTransaction:
    """One purchased line item, in the common Amazon + Weee! schema."""

    txn_id: str
    order_id: str
    purchased_on: date
    channel: str  # "Amazon" | "Weee!" | ...
    merchant: str  # seller of record; for Weee! this is the channel
    item: str  # normalized item name
    category: str  # full path, e.g. "Groceries > Coffee"
    quantity: float
    unit_price: float
    line_spend: float
    raw_item: str
    brand: str | None = None
    attributes: list[str] = field(default_factory=list)
    condition: Condition = Condition.UNKNOWN
    model_weight: float = 1.0  # signal reliability shipped with the source data
    source_sheet: str = ""

    @property
    def category_top(self) -> str:
        return self.category.split(">")[0].strip()

    @property
    def category_leaf(self) -> str:
        return self.category.split(">")[-1].strip()

    def to_dict(self) -> dict[str, Any]:
        return jsonify(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NormalizedTransaction":
        data = dict(payload)
        raw_date = data.get("purchased_on")
        if isinstance(raw_date, str):
            data["purchased_on"] = date.fromisoformat(raw_date)
        data["condition"] = Condition(data.get("condition", "UNKNOWN"))
        data.setdefault("attributes", [])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ExcludedTransaction:
    """A line the noise filter removed, kept so exclusions stay auditable."""

    raw_item: str
    category: str
    channel: str
    reason: str
    rule: str
    order_id: str = ""
    purchased_on: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonify(asdict(self))


# --------------------------------------------------------------------------
# Item and category profiles
# --------------------------------------------------------------------------


@dataclass
class PriceStats:
    minimum: float
    p10: float
    median: float
    p90: float
    maximum: float
    mean: float
    samples: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "min": round(self.minimum, 2),
            "p10": round(self.p10, 2),
            "median": round(self.median, 2),
            "p90": round(self.p90, 2),
            "max": round(self.maximum, 2),
            "mean": round(self.mean, 2),
            "samples": self.samples,
        }


@dataclass
class ItemProfile:
    item: str
    categories: list[str]
    channels: list[str]
    occasions: int  # distinct orders containing the item
    total_quantity: float
    total_spend: float
    unit_price: PriceStats
    first_purchased: date
    last_purchased: date
    repeat_behavior: RepeatBehavior
    cadence_days: float | None
    cadence_source: CadenceSource
    cadence_samples: int
    next_due_on: date | None
    brand_shares: dict[str, float]
    attribute_rates: dict[str, float]
    evidence_weight: float
    confidence: float
    negative_signals: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = jsonify(asdict(self))
        payload["unit_price"] = self.unit_price.to_dict()
        payload["confidence_band"] = band_for(self.confidence).value
        return payload


@dataclass
class CategoryProfile:
    category: str
    channels: list[str]
    orders_with_category: int
    penetration_household: float  # share of all orders containing this category
    penetration_by_channel: dict[str, float]
    line_items: int
    unique_items: int
    total_quantity: float
    total_spend: float
    spend_share: float
    unit_price: PriceStats
    first_purchased: date
    last_purchased: date
    monthly_occasions: float | None
    cadence_source: CadenceSource
    price_sensitivity: PreferenceSignal
    quality_importance: PreferenceSignal
    brand_loyalty: PreferenceSignal
    top_items: list[str]
    preferred_channel: str | None
    evidence_weight: float
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        payload = jsonify(asdict(self))
        payload["unit_price"] = self.unit_price.to_dict()
        payload["price_sensitivity"] = self.price_sensitivity.to_dict()
        payload["quality_importance"] = self.quality_importance.to_dict()
        payload["brand_loyalty"] = self.brand_loyalty.to_dict()
        payload["confidence_band"] = band_for(self.confidence).value
        return payload


# --------------------------------------------------------------------------
# BuyerPreferenceProfile (PRD section 6 shared contract)
# --------------------------------------------------------------------------


@dataclass
class BuyerPreferenceProfile:
    """The shared contract. `category` is None for the general buyer profile."""

    buyer_id: str
    category: str | None
    price_sensitivity: PreferenceSignal
    observed_price_range: PreferenceSignal
    quality_importance: PreferenceSignal
    delivery_importance: PreferenceSignal
    returns_importance: PreferenceSignal
    preferred_brands: PreferenceSignal
    disliked_brands: PreferenceSignal
    condition_preference: PreferenceSignal
    channel_preference: PreferenceSignal
    repeat_behavior: PreferenceSignal
    replenishment_cadence_days: PreferenceSignal
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    _SIGNAL_FIELDS = (
        "price_sensitivity",
        "observed_price_range",
        "quality_importance",
        "delivery_importance",
        "returns_importance",
        "preferred_brands",
        "disliked_brands",
        "condition_preference",
        "channel_preference",
        "repeat_behavior",
        "replenishment_cadence_days",
    )

    def signals(self) -> dict[str, PreferenceSignal]:
        return {name: getattr(self, name) for name in self._SIGNAL_FIELDS}

    def unknowns(self) -> list[str]:
        """Preference names this profile genuinely cannot speak to."""
        return [name for name, sig in self.signals().items() if not sig.observable]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "buyer_id": self.buyer_id,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "confidence_band": band_for(self.confidence).value,
            "notes": list(self.notes),
            "unknowns": self.unknowns(),
        }
        for name, signal in self.signals().items():
            payload[name] = signal.to_dict()
        return payload

    def to_mandate_hints(self) -> dict[str, Any]:
        """Soft preferences for the Mandate Engine.

        Deliberately emits no MUST / MUST NOT entries. Behaviour is evidence, so
        every value here belongs under PREFER, and current explicit intent
        outranks all of it.
        """
        return {
            "buyer_id": self.buyer_id,
            "category": self.category,
            "prefer": {
                name: signal.to_dict()
                for name, signal in self.signals().items()
                if signal.observable and signal.confidence > 0
            },
            "unknown": {
                name: signal.evidence
                for name, signal in self.signals().items()
                if not signal.observable
            },
            "hard_constraints": [],
            "note": (
                "Learned from purchase history. Evidence only -- never a hard "
                "mandate. Current explicit intent overrides every value here."
            ),
        }


# --------------------------------------------------------------------------
# Versioned bundle
# --------------------------------------------------------------------------


@dataclass
class ProfileRevision:
    version: int
    created_on: date
    reason: str
    transactions_added: int = 0
    feedback_applied: int = 0
    changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonify(asdict(self))


@dataclass
class FeedbackEvent:
    """Post-recommendation signal used to correct the profile."""

    kind: FeedbackKind
    item: str | None = None
    category: str | None = None
    brand: str | None = None
    channel: str | None = None
    occurred_on: date | None = None
    detail: str = ""
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return jsonify(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeedbackEvent":
        data = dict(payload)
        data["kind"] = FeedbackKind(data["kind"])
        if isinstance(data.get("occurred_on"), str):
            data["occurred_on"] = date.fromisoformat(data["occurred_on"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class BuyerProfileBundle:
    """Everything the module knows about one buyer, at one version.

    The bundle carries its own transaction ledger. `update_profile` re-derives
    every profile from the full ledger rather than patching values in place, so
    a given (ledger, feedback, as_of) always yields the same profile -- no drift
    across updates and no model retraining.
    """

    buyer_id: str
    version: int
    as_of: date
    general: BuyerPreferenceProfile
    categories: dict[str, BuyerPreferenceProfile]
    category_profiles: dict[str, CategoryProfile]
    item_profiles: dict[str, ItemProfile]
    transactions: list[NormalizedTransaction] = field(default_factory=list)
    feedback: list[FeedbackEvent] = field(default_factory=list)
    excluded: list[ExcludedTransaction] = field(default_factory=list)
    revisions: list[ProfileRevision] = field(default_factory=list)
    # Cadence priors supplied by the source data, carried across rebuilds.
    modeled_monthly_occasions: dict[tuple[str, str], float] = field(default_factory=dict)
    modeled_category_occasions: dict[tuple[str, str], float] = field(default_factory=dict)

    def profile_for(self, category: str | None) -> BuyerPreferenceProfile:
        """Category profile when one exists, otherwise the general profile."""
        if category and category in self.categories:
            return self.categories[category]
        return self.general

    def to_dict(self) -> dict[str, Any]:
        return {
            "buyer_id": self.buyer_id,
            "version": self.version,
            "as_of": self.as_of.isoformat(),
            "general": self.general.to_dict(),
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
            "revisions": [r.to_dict() for r in self.revisions],
            "counts": {
                "transactions": len(self.transactions),
                "excluded": len(self.excluded),
                "feedback": len(self.feedback),
                "categories": len(self.category_profiles),
                "items": len(self.item_profiles),
            },
        }


# --------------------------------------------------------------------------
# Prediction contracts
# --------------------------------------------------------------------------


@dataclass
class PurchaseCandidate:
    """A product being considered. Mirrors the shared TransactionCandidate."""

    candidate_id: str
    item: str
    category: str
    unit_price: float
    brand: str | None = None
    merchant: str | None = None
    channel: str | None = None
    quantity: float = 1.0
    condition: Condition = Condition.UNKNOWN
    attributes: list[str] = field(default_factory=list)
    delivery_days: int | None = None
    return_window_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonify(asdict(self))


@dataclass
class PredictionContext:
    """When and where the decision is being made, plus any explicit intent."""

    as_of: date
    channel: str | None = None
    # Explicit buyer intent for this mission. Outranks everything learned.
    explicit_preferences: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return jsonify(asdict(self))


@dataclass
class Driver:
    """One named, signed contribution to the prediction."""

    name: str
    contribution: float  # in log-odds
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "contribution": round(self.contribution, 4),
            "explanation": self.explanation,
        }


@dataclass
class PurchasePrediction:
    probability: float
    confidence: float
    positive_drivers: list[Driver]
    negative_drivers: list[Driver]
    unknowns: list[str]
    matched: dict[str, Any]
    profile_version: int
    base_rate: float

    @property
    def confidence_band(self) -> ConfidenceBand:
        return band_for(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "confidence_band": self.confidence_band.value,
            "base_rate": round(self.base_rate, 4),
            "positive_drivers": [d.to_dict() for d in self.positive_drivers],
            "negative_drivers": [d.to_dict() for d in self.negative_drivers],
            "unknowns": list(self.unknowns),
            "matched": jsonify(self.matched),
            "profile_version": self.profile_version,
        }

    def explain(self) -> str:
        lines = [
            f"P(buy) = {self.probability:.3f} "
            f"(confidence {self.confidence:.2f} / {self.confidence_band.value})"
        ]
        for driver in self.positive_drivers:
            lines.append(f"  + {driver.name:<24} {driver.contribution:+.2f}  {driver.explanation}")
        for driver in self.negative_drivers:
            lines.append(f"  - {driver.name:<24} {driver.contribution:+.2f}  {driver.explanation}")
        for unknown in self.unknowns:
            lines.append(f"  ? {unknown}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Serialization helper
# --------------------------------------------------------------------------


def jsonify(value: Any) -> Any:
    """Recursively convert dataclasses, enums and dates into JSON-safe values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return jsonify(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonify(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value
