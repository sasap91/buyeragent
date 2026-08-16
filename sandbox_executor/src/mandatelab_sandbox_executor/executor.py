from __future__ import annotations

from datetime import datetime, timezone

from mandatelab_contracts import (
    ApprovalRequirement,
    CartSnapshot,
    ConstraintStatus,
    Decision,
    DecisionResult,
    TransactionOutcome,
    TransactionOutcomeStatus,
)


DECISION_NOT_APPROVED = "DECISION_NOT_APPROVED"
HUMAN_APPROVAL_UNRESOLVED = "HUMAN_APPROVAL_UNRESOLVED"
DECISION_HAS_VIOLATIONS = "DECISION_HAS_VIOLATIONS"
DECISION_CART_ID_MISMATCH = "DECISION_CART_ID_MISMATCH"
DECISION_CART_FINGERPRINT_MISMATCH = "DECISION_CART_FINGERPRINT_MISMATCH"
DECISION_CANDIDATE_MISMATCH = "DECISION_CANDIDATE_MISMATCH"
DECISION_FROM_FUTURE = "DECISION_FROM_FUTURE"
CART_ALREADY_EXECUTED = "CART_ALREADY_EXECUTED"


class InMemorySandboxExecutor:
    """Controlled executor with an append-only in-memory outcome ledger."""

    def __init__(self) -> None:
        self._ledger: list[TransactionOutcome] = []
        self._executed_by_cart: dict[str, TransactionOutcome] = {}
        self._executed_fingerprints: dict[str, str] = {}
        self._executed_decisions: dict[str, DecisionResult] = {}

    @property
    def ledger(self) -> tuple[TransactionOutcome, ...]:
        """Return an immutable snapshot of all execution attempts."""

        return tuple(self._ledger)

    def _not_executed(
        self,
        cart: CartSnapshot,
        decision: DecisionResult,
        reason: str,
        occurred_at: datetime,
        outcome_id: str | None,
    ) -> TransactionOutcome:
        outcome = TransactionOutcome(
            outcome_id=(
                outcome_id
                or f"outcome:{decision.decision_id}:{reason.lower()}"
            ),
            status=TransactionOutcomeStatus.NOT_EXECUTED,
            cart_id=cart.cart_id,
            decision_id=decision.decision_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        self._ledger.append(outcome)
        return outcome

    def execute(
        self,
        cart: CartSnapshot,
        decision: DecisionResult,
        *,
        occurred_at: datetime | None = None,
        outcome_id: str | None = None,
        transaction_id: str | None = None,
    ) -> TransactionOutcome:
        """Attempt one sandbox transaction without external side effects."""

        timestamp = occurred_at or datetime.now(timezone.utc)

        previous = self._executed_by_cart.get(cart.cart_id)
        if previous is not None:
            same_request = (
                self._executed_decisions[cart.cart_id] == decision
                and self._executed_fingerprints[cart.cart_id]
                == cart.cart_fingerprint
            )
            if same_request:
                return previous
            return self._not_executed(
                cart,
                decision,
                CART_ALREADY_EXECUTED,
                timestamp,
                outcome_id,
            )

        rejection_reason = self._rejection_reason(cart, decision, timestamp)
        if rejection_reason is not None:
            return self._not_executed(
                cart,
                decision,
                rejection_reason,
                timestamp,
                outcome_id,
            )

        outcome = TransactionOutcome(
            outcome_id=outcome_id or f"outcome:{decision.decision_id}",
            status=TransactionOutcomeStatus.EXECUTED,
            cart_id=cart.cart_id,
            decision_id=decision.decision_id,
            transaction_id=(
                transaction_id
                or f"sandbox:{cart.cart_id}:{decision.decision_id}"
            ),
            occurred_at=timestamp,
        )
        self._ledger.append(outcome)
        self._executed_by_cart[cart.cart_id] = outcome
        self._executed_fingerprints[cart.cart_id] = cart.cart_fingerprint
        self._executed_decisions[cart.cart_id] = decision
        return outcome

    @staticmethod
    def _rejection_reason(
        cart: CartSnapshot,
        decision: DecisionResult,
        occurred_at: datetime,
    ) -> str | None:
        if decision.decision is not Decision.APPROVE:
            return DECISION_NOT_APPROVED
        if decision.approval_requirement is not ApprovalRequirement.NONE:
            return HUMAN_APPROVAL_UNRESOLVED
        if decision.violations or any(
            result.status is ConstraintStatus.FAIL
            for result in decision.constraint_results
        ):
            return DECISION_HAS_VIOLATIONS
        if decision.cart_id != cart.cart_id:
            return DECISION_CART_ID_MISMATCH
        if decision.cart_fingerprint != cart.cart_fingerprint:
            return DECISION_CART_FINGERPRINT_MISMATCH
        if decision.candidate_id != cart.candidate_id:
            return DECISION_CANDIDATE_MISMATCH
        if decision.evaluated_at > occurred_at:
            return DECISION_FROM_FUTURE
        return None


def execute_sandbox(
    cart: CartSnapshot,
    decision: DecisionResult,
    *,
    executor: InMemorySandboxExecutor | None = None,
    occurred_at: datetime | None = None,
    outcome_id: str | None = None,
    transaction_id: str | None = None,
) -> TransactionOutcome:
    """Execute through a provided sandbox ledger or a one-shot executor."""

    sandbox = executor or InMemorySandboxExecutor()
    return sandbox.execute(
        cart,
        decision,
        occurred_at=occurred_at,
        outcome_id=outcome_id,
        transaction_id=transaction_id,
    )
