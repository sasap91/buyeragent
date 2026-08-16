from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Generic, Literal, TypeAlias, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]
UnitDecimal = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1")),
]
PositiveInt = Annotated[int, Field(ge=1)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ContractModel(BaseModel):
    """Strict base model shared by all MandateLab contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ImportanceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PreferenceSource(str, Enum):
    CURRENT_EXPLICIT = "CURRENT_EXPLICIT"
    COLD_START = "COLD_START"
    CATEGORY_HISTORY = "CATEGORY_HISTORY"
    GENERAL_HISTORY = "GENERAL_HISTORY"
    DEFAULT = "DEFAULT"


class MandateSource(str, Enum):
    CURRENT_EXPLICIT = "CURRENT_EXPLICIT"
    CONFIRMED_PROFILE_RULE = "CONFIRMED_PROFILE_RULE"
    INFERRED = "INFERRED"


class ProductCondition(str, Enum):
    NEW = "NEW"
    REFURBISHED = "REFURBISHED"
    USED = "USED"


class ConstraintKind(str, Enum):
    MAX_LANDED_PRICE = "MAX_LANDED_PRICE"
    ALLOWED_CONDITION = "ALLOWED_CONDITION"
    REQUIRED_FEATURES = "REQUIRED_FEATURES"
    DELIVERY_BY = "DELIVERY_BY"
    ALLOWED_MERCHANT = "ALLOWED_MERCHANT"
    PRODUCT_ID = "PRODUCT_ID"
    VARIANT_ID = "VARIANT_ID"


class ConstraintOperator(str, Enum):
    LTE = "LTE"
    EQ = "EQ"
    IN = "IN"
    CONTAINS_ALL = "CONTAINS_ALL"
    ON_OR_BEFORE = "ON_OR_BEFORE"


class PreferenceAttribute(str, Enum):
    PRICE = "PRICE"
    QUALITY = "QUALITY"
    BRAND = "BRAND"
    DELIVERY = "DELIVERY"
    RETURN_POLICY = "RETURN_POLICY"
    MERCHANT_TRUST = "MERCHANT_TRUST"
    CONDITION = "CONDITION"


class PreferenceDirection(str, Enum):
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"
    PREFER = "PREFER"
    AVOID = "AVOID"


class MaterialCartField(str, Enum):
    PRODUCT_ID = "PRODUCT_ID"
    VARIANT_ID = "VARIANT_ID"
    FINAL_LANDED_PRICE = "FINAL_LANDED_PRICE"
    CONDITION = "CONDITION"
    MERCHANT = "MERCHANT"
    DELIVERY_DATE = "DELIVERY_DATE"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class ConstraintStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ApprovalRequirement(str, Enum):
    NONE = "NONE"
    HUMAN = "HUMAN"


class TransactionOutcomeStatus(str, Enum):
    EXECUTED = "EXECUTED"
    NOT_EXECUTED = "NOT_EXECUTED"


class Money(ContractModel):
    amount: NonNegativeDecimal
    currency: Literal["USD"] = "USD"


ConstraintValue: TypeAlias = Money | date | bool | list[str] | str


SignalValue = TypeVar("SignalValue")


class PreferenceSignal(ContractModel, Generic[SignalValue]):
    value: SignalValue
    numeric_weight: UnitDecimal
    source: PreferenceSource
    confidence: UnitDecimal


class HardRuleCandidate(ContractModel):
    candidate_id: NonEmptyStr
    kind: ConstraintKind
    operator: ConstraintOperator
    expected: ConstraintValue = Field(union_mode="left_to_right")
    source: PreferenceSource
    confidence: UnitDecimal
    requires_confirmation: bool = True
    rationale: NonEmptyStr | None = None


class BuyerPreferenceProfile(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    buyer_id: NonEmptyStr
    category: NonEmptyStr
    price_sensitivity: PreferenceSignal[ImportanceLevel]
    quality_importance: PreferenceSignal[ImportanceLevel]
    delivery_importance: PreferenceSignal[ImportanceLevel]
    return_policy_importance: PreferenceSignal[ImportanceLevel]
    merchant_trust_importance: PreferenceSignal[ImportanceLevel]
    preferred_brands: list[PreferenceSignal[NonEmptyStr]] = Field(default_factory=list)
    disliked_brands: list[PreferenceSignal[NonEmptyStr]] = Field(default_factory=list)
    condition_preferences: list[PreferenceSignal[ProductCondition]] = Field(
        default_factory=list
    )
    hard_rule_candidates: list[HardRuleCandidate] = Field(default_factory=list)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def brands_cannot_be_both_preferred_and_disliked(self) -> BuyerPreferenceProfile:
        preferred = {signal.value.casefold() for signal in self.preferred_brands}
        disliked = {signal.value.casefold() for signal in self.disliked_brands}
        overlap = preferred & disliked
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"brands cannot be both preferred and disliked: {names}")
        return self


class AuthorizationPolicy(ContractModel):
    autonomous_spend_limit: Money
    maximum_authorized_total: Money
    substitution_allowed: bool = False
    material_change_fields: list[MaterialCartField] = Field(
        default_factory=lambda: list(MaterialCartField)
    )

    @model_validator(mode="after")
    def maximum_must_cover_autonomous_limit(self) -> AuthorizationPolicy:
        if self.maximum_authorized_total.amount < self.autonomous_spend_limit.amount:
            raise ValueError(
                "maximum_authorized_total must be greater than or equal to "
                "autonomous_spend_limit"
            )
        return self


class HardConstraint(ContractModel):
    constraint_id: NonEmptyStr
    kind: ConstraintKind
    operator: ConstraintOperator
    expected: ConstraintValue = Field(union_mode="left_to_right")
    required: bool = True
    source: MandateSource
    confidence: UnitDecimal = Decimal("1")


class SoftPreference(ContractModel):
    preference_id: NonEmptyStr
    attribute: PreferenceAttribute
    direction: PreferenceDirection
    preferred_value: ConstraintValue = Field(union_mode="left_to_right")
    weight: UnitDecimal
    source: PreferenceSource
    confidence: UnitDecimal


class PurchaseIntent(ContractModel):
    intent_id: NonEmptyStr
    buyer_id: NonEmptyStr
    raw_text: NonEmptyStr
    goal: NonEmptyStr | None = None
    category: NonEmptyStr | None = None
    hard_constraints: list[HardConstraint] = Field(default_factory=list)
    soft_preferences: list[SoftPreference] = Field(default_factory=list)
    authorization: AuthorizationPolicy | None = None
    material_ambiguities: list[NonEmptyStr] = Field(default_factory=list)
    created_at: AwareDatetime


class Mandate(ContractModel):
    mandate_id: NonEmptyStr
    version: PositiveInt = 1
    buyer_id: NonEmptyStr
    goal: NonEmptyStr
    category: NonEmptyStr
    hard_constraints: list[HardConstraint] = Field(default_factory=list)
    soft_preferences: list[SoftPreference] = Field(default_factory=list)
    authorization: AuthorizationPolicy
    material_ambiguities: list[NonEmptyStr] = Field(default_factory=list)
    created_at: AwareDatetime


class ReturnPolicy(ContractModel):
    returnable: bool | None = None
    window_days: Annotated[int, Field(ge=0)] | None = None
    summary: NonEmptyStr | None = None


class TransactionCandidate(ContractModel):
    candidate_id: NonEmptyStr
    product_id: NonEmptyStr
    variant_id: NonEmptyStr | None = None
    product_name: NonEmptyStr
    brand: NonEmptyStr | None = None
    condition: ProductCondition | None = None
    features: list[NonEmptyStr] | None = None
    merchant: NonEmptyStr | None = None
    item_price: Money | None = None
    shipping: Money | None = None
    fees: Money | None = None
    final_landed_price: Money | None = None
    delivery_date: date | None = None
    return_policy: ReturnPolicy | None = None
    observed_at: AwareDatetime

    @field_validator("features")
    @classmethod
    def features_must_be_unique(cls, features: list[str] | None) -> list[str] | None:
        if features is not None and len({item.casefold() for item in features}) != len(
            features
        ):
            raise ValueError("features must be unique")
        return features


class CartSnapshot(TransactionCandidate):
    cart_id: NonEmptyStr
    cart_fingerprint: Sha256Hex


class ConstraintResult(ContractModel):
    constraint_id: NonEmptyStr
    status: ConstraintStatus
    expected: ConstraintValue = Field(union_mode="left_to_right")
    actual: ConstraintValue | None = Field(default=None, union_mode="left_to_right")
    code: NonEmptyStr
    explanation: NonEmptyStr


class Violation(ContractModel):
    code: NonEmptyStr
    message: NonEmptyStr
    constraint_id: NonEmptyStr | None = None
    expected: ConstraintValue | None = Field(default=None, union_mode="left_to_right")
    actual: ConstraintValue | None = Field(default=None, union_mode="left_to_right")


class ReplanInstruction(ContractModel):
    reason_codes: list[NonEmptyStr]
    required_constraints: list[HardConstraint] = Field(default_factory=list)
    exclude_candidate_ids: list[NonEmptyStr] = Field(default_factory=list)
    message: NonEmptyStr


class RankingExplanation(ContractModel):
    total_score: UnitDecimal
    component_scores: dict[PreferenceAttribute, UnitDecimal] = Field(
        default_factory=dict
    )
    influential_preferences: list[NonEmptyStr] = Field(default_factory=list)
    summary: NonEmptyStr


class DecisionResult(ContractModel):
    decision_id: NonEmptyStr
    decision: Decision
    mandate_id: NonEmptyStr
    mandate_version: PositiveInt
    candidate_id: NonEmptyStr | None = None
    cart_id: NonEmptyStr | None = None
    cart_fingerprint: Sha256Hex | None = None
    constraint_results: list[ConstraintResult] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    warnings: list[NonEmptyStr] = Field(default_factory=list)
    ranking_explanation: RankingExplanation | None = None
    approval_requirement: ApprovalRequirement = ApprovalRequirement.NONE
    replan_instruction: ReplanInstruction | None = None
    evaluated_at: AwareDatetime


class HumanApproval(ContractModel):
    approval_id: NonEmptyStr
    mandate_id: NonEmptyStr
    mandate_version: PositiveInt
    cart_id: NonEmptyStr
    cart_fingerprint: Sha256Hex
    approver_id: NonEmptyStr
    approved_at: AwareDatetime
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def expiry_must_follow_approval(self) -> HumanApproval:
        if self.expires_at is not None and self.expires_at <= self.approved_at:
            raise ValueError("expires_at must be later than approved_at")
        return self


class TransactionOutcome(ContractModel):
    outcome_id: NonEmptyStr
    status: TransactionOutcomeStatus
    cart_id: NonEmptyStr
    decision_id: NonEmptyStr
    transaction_id: NonEmptyStr | None = None
    reason: NonEmptyStr | None = None
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def executed_outcome_requires_transaction_id(self) -> TransactionOutcome:
        if (
            self.status is TransactionOutcomeStatus.EXECUTED
            and self.transaction_id is None
        ):
            raise ValueError("transaction_id is required when status is EXECUTED")
        return self
