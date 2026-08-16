"""RL-ready trajectory logging.

Nothing here trains anything. The point is to record each shopping mission in a
shape that offline preference learning, contextual bandits or offline RL could
consume later:

    buyer state -> intent -> candidates -> action -> decision
                -> outcome -> feedback -> reward signals

Reward components are computed deterministically from what was logged, so a
trajectory file can be replayed and rescored without re-running the agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from buyer_history.schema import (
    BuyerProfileBundle,
    FeedbackEvent,
    PurchaseCandidate,
    PurchasePrediction,
    jsonify,
)


class ActionType(str, Enum):
    RECOMMEND = "RECOMMEND"
    EXECUTE = "EXECUTE"
    ESCALATE = "ESCALATE"
    REPLAN = "REPLAN"
    ABORT = "ABORT"


class Decision(str, Enum):
    """Mirrors the Decision Engine's contract. This module only records it."""

    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass
class CandidateRecord:
    """A candidate as it was scored at decision time."""

    candidate: PurchaseCandidate
    prediction: PurchasePrediction
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "prediction": self.prediction.to_dict(),
            "selected": self.selected,
        }


@dataclass
class Outcome:
    purchased: bool = False
    final_price: float | None = None
    reference_price: float | None = None  # what the buyer usually pays
    aborted_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonify(self)


@dataclass
class RewardSignals:
    """PRD section 7 reward dimensions, plus the hard-failure flags."""

    successful_permissible_purchase: float = 0.0
    buyer_preference_fit: float = 0.0
    economic_value: float = 0.0
    correct_autonomous_action: float = 0.0
    correct_escalation: float = 0.0
    unnecessary_interruption: float = 0.0
    negative_feedback: float = 0.0
    hard_failures: list[str] = field(default_factory=list)
    total: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return jsonify(self)


# Weights are a stated starting point for offline scoring, not a learned policy.
REWARD_WEIGHTS: dict[str, float] = {
    "successful_permissible_purchase": 1.0,
    "buyer_preference_fit": 1.0,
    "economic_value": 0.5,
    "correct_autonomous_action": 0.5,
    "correct_escalation": 0.5,
    "unnecessary_interruption": 1.0,
    "negative_feedback": 1.0,
}
HARD_FAILURE_PENALTY = -5.0


@dataclass
class ShoppingTrajectory:
    """One mission, start to finish."""

    trajectory_id: str
    buyer_id: str
    occurred_on: date
    buyer_state: dict[str, Any] = field(default_factory=dict)
    intent: dict[str, Any] = field(default_factory=dict)
    mandate_ref: str | None = None
    candidates: list[CandidateRecord] = field(default_factory=list)
    action: dict[str, Any] = field(default_factory=dict)
    decision: Decision | None = None
    constraint_results: dict[str, str] = field(default_factory=dict)
    outcome: Outcome = field(default_factory=Outcome)
    feedback: list[FeedbackEvent] = field(default_factory=list)
    rewards: RewardSignals | None = None

    def selected(self) -> CandidateRecord | None:
        for record in self.candidates:
            if record.selected:
                return record
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "buyer_id": self.buyer_id,
            "occurred_on": self.occurred_on.isoformat(),
            "buyer_state": jsonify(self.buyer_state),
            "intent": jsonify(self.intent),
            "mandate_ref": self.mandate_ref,
            "candidates": [c.to_dict() for c in self.candidates],
            "action": jsonify(self.action),
            "decision": self.decision.value if self.decision else None,
            "constraint_results": dict(self.constraint_results),
            "outcome": self.outcome.to_dict(),
            "feedback": [f.to_dict() for f in self.feedback],
            "rewards": self.rewards.to_dict() if self.rewards else None,
        }


def buyer_state_of(bundle: BuyerProfileBundle, category: str | None = None) -> dict[str, Any]:
    """A compact, replayable snapshot of the profile a decision was made against."""
    preference = bundle.profile_for(category)
    return {
        "buyer_id": bundle.buyer_id,
        "profile_version": bundle.version,
        "as_of": bundle.as_of.isoformat(),
        "scope": preference.category or "general",
        "price_sensitivity": jsonify(preference.price_sensitivity.value),
        "quality_importance": jsonify(preference.quality_importance.value),
        "confidence": preference.confidence,
        "unknowns": preference.unknowns(),
        "transactions_in_ledger": len(bundle.transactions),
    }


def compute_rewards(trajectory: ShoppingTrajectory) -> RewardSignals:
    """Score a completed trajectory. Deterministic; safe to replay."""
    rewards = RewardSignals()
    selected = trajectory.selected()
    decision = trajectory.decision
    action = str(trajectory.action.get("type", ""))
    outcome = trajectory.outcome

    if selected:
        rewards.buyer_preference_fit = round(selected.prediction.probability, 4)

    if outcome.purchased:
        if decision is Decision.APPROVE:
            rewards.successful_permissible_purchase = 1.0
            rewards.correct_autonomous_action = 1.0
        if decision is Decision.BLOCK:
            rewards.hard_failures.append("EXECUTION_AFTER_BLOCK")
        if decision is Decision.REVIEW and not trajectory.action.get("human_approval_ref"):
            rewards.hard_failures.append("EXECUTION_AFTER_UNRESOLVED_REVIEW")

    if decision is Decision.REVIEW and action == ActionType.ESCALATE.value:
        rewards.correct_escalation = 1.0
        # Escalating a transaction that had nothing to resolve is a real cost:
        # it spends the buyer's attention for no decision.
        if not trajectory.action.get("escalation_reason"):
            rewards.unnecessary_interruption = -0.5

    if outcome.final_price is not None and outcome.reference_price:
        saving = (outcome.reference_price - outcome.final_price) / outcome.reference_price
        rewards.economic_value = round(max(-1.0, min(1.0, saving)), 4)

    for event in trajectory.feedback:
        if event.kind.value in ("RETURN", "CANCELLATION"):
            rewards.negative_feedback -= 1.0
        elif event.kind.value == "RECOMMENDATION_REJECTED":
            rewards.negative_feedback -= 0.5

    for code, result in trajectory.constraint_results.items():
        if result == "FAIL" and outcome.purchased:
            rewards.hard_failures.append(f"HARD_MANDATE_VIOLATION:{code}")
        if result == "UNKNOWN" and outcome.purchased and decision is not Decision.APPROVE:
            rewards.hard_failures.append(f"EXECUTED_WITH_UNKNOWN_CONSTRAINT:{code}")

    total = sum(
        REWARD_WEIGHTS[name] * getattr(rewards, name) for name in REWARD_WEIGHTS
    )
    total += HARD_FAILURE_PENALTY * len(rewards.hard_failures)
    rewards.total = round(total, 4)
    return rewards


class EventStore:
    """Append-only JSONL trajectory log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, trajectory: ShoppingTrajectory) -> ShoppingTrajectory:
        if trajectory.rewards is None:
            trajectory.rewards = compute_rewards(trajectory)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trajectory.to_dict(), ensure_ascii=False) + "\n")
        return trajectory

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
