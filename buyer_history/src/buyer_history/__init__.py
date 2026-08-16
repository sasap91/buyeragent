"""MandateLab -- Existing Buyer Preference Learning (PRD section 5.2).

Infers a BuyerPreferenceProfile from real purchase behaviour, predicts purchase
likelihood with an explainable model, and updates the profile as new
transactions and feedback arrive.

Two invariants hold throughout:
  * Purchase history is evidence, not ground truth. Current explicit intent
    always outranks anything learned here.
  * Nothing in this module emits a hard mandate. Behaviour produces soft
    preferences only; the Mandate Engine owns constraints and enforcement.
"""

from buyer_history.events import (
    ActionType,
    CandidateRecord,
    Decision,
    EventStore,
    Outcome,
    RewardSignals,
    ShoppingTrajectory,
    buyer_state_of,
    compute_rewards,
)
from buyer_history.export import export_bundle
from buyer_history.infer import (
    build_category_profiles,
    build_item_profiles,
    build_preference_profile,
    resolve_category_key,
)
from buyer_history.noise import NoiseFilter, NoiseRule
from buyer_history.normalize import (
    LoadedHistory,
    extract_attributes,
    extract_brand,
    load_workbook_history,
)
from buyer_history.predict import predict_purchase_probability
from buyer_history.schema import (
    BuyerPreferenceProfile,
    BuyerProfileBundle,
    CadenceSource,
    CategoryProfile,
    Condition,
    ConfidenceBand,
    Driver,
    ExcludedTransaction,
    FeedbackEvent,
    FeedbackKind,
    Importance,
    ItemProfile,
    NormalizedTransaction,
    PredictionContext,
    PreferenceSignal,
    PriceStats,
    ProfileRevision,
    PurchaseCandidate,
    PurchasePrediction,
    RepeatBehavior,
    Source,
)
from buyer_history.update import (
    build_profile,
    build_profile_from_workbook,
    record_purchase,
    update_profile,
)

__all__ = [
    "ActionType",
    "BuyerPreferenceProfile",
    "BuyerProfileBundle",
    "CadenceSource",
    "CandidateRecord",
    "CategoryProfile",
    "Condition",
    "ConfidenceBand",
    "Decision",
    "Driver",
    "EventStore",
    "ExcludedTransaction",
    "FeedbackEvent",
    "FeedbackKind",
    "Importance",
    "ItemProfile",
    "LoadedHistory",
    "NoiseFilter",
    "NoiseRule",
    "NormalizedTransaction",
    "Outcome",
    "PredictionContext",
    "PreferenceSignal",
    "PriceStats",
    "ProfileRevision",
    "PurchaseCandidate",
    "PurchasePrediction",
    "RepeatBehavior",
    "RewardSignals",
    "ShoppingTrajectory",
    "Source",
    "build_category_profiles",
    "build_item_profiles",
    "build_preference_profile",
    "build_profile",
    "build_profile_from_workbook",
    "buyer_state_of",
    "compute_rewards",
    "export_bundle",
    "extract_attributes",
    "extract_brand",
    "load_workbook_history",
    "predict_purchase_probability",
    "record_purchase",
    "resolve_category_key",
    "update_profile",
]
