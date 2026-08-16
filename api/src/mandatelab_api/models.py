from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mandatelab_contracts import (
    AuthorizationPolicy,
    BuyerPreferenceProfile,
    CartSnapshot,
    DecisionResult,
    HumanApproval,
    Mandate,
    PurchaseIntent,
    RankingExplanation,
    TransactionCandidate,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"


class ParseMandateRequest(ApiModel):
    intent: PurchaseIntent
    profile: BuyerPreferenceProfile
    default_authorization: AuthorizationPolicy | None = None
    mandate_id: str | None = None
    version: int = Field(default=1, ge=1)


class RankCandidatesRequest(ApiModel):
    candidates: list[TransactionCandidate]
    mandate: Mandate
    profile: BuyerPreferenceProfile


class RankedCandidateResponse(ApiModel):
    candidate: TransactionCandidate
    explanation: RankingExplanation


class EvaluateCandidateRequest(ApiModel):
    candidate: TransactionCandidate
    mandate: Mandate
    decision_id: str | None = None
    evaluated_at: datetime | None = None


class ValidatePrecheckoutRequest(ApiModel):
    cart: CartSnapshot
    mandate: Mandate
    approval: HumanApproval | None = None
    decision_id: str | None = None
    evaluated_at: datetime | None = None


class ExecuteSandboxRequest(ApiModel):
    cart: CartSnapshot
    decision: DecisionResult
    occurred_at: datetime | None = None
    outcome_id: str | None = None
    transaction_id: str | None = None
