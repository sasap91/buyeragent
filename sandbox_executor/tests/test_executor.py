from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mandatelab_contracts import (
    ApprovalRequirement,
    CartSnapshot,
    Decision,
    DecisionResult,
    Money,
    ProductCondition,
    TransactionOutcome,
    TransactionOutcomeStatus,
    Violation,
)
from mandatelab_sandbox_executor import (
    CART_ALREADY_EXECUTED,
    DECISION_CANDIDATE_MISMATCH,
    DECISION_CART_FINGERPRINT_MISMATCH,
    DECISION_CART_ID_MISMATCH,
    DECISION_FROM_FUTURE,
    DECISION_HAS_VIOLATIONS,
    DECISION_NOT_APPROVED,
    HUMAN_APPROVAL_UNRESOLVED,
    InMemorySandboxExecutor,
    execute_sandbox,
)


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
EXECUTION_TIME = NOW + timedelta(minutes=1)
FINGERPRINT = "a" * 64


def cart(**updates: object) -> CartSnapshot:
    payload: dict[str, object] = {
        "candidate_id": "candidate-sony-black",
        "product_id": "sony-wh-1000xm5",
        "variant_id": "black",
        "product_name": "Sony WH-1000XM5",
        "brand": "Sony",
        "condition": ProductCondition.NEW,
        "features": ["active-noise-cancelling", "bluetooth"],
        "merchant": "MandateMart",
        "final_landed_price": Money(amount="150"),
        "observed_at": NOW,
        "cart_id": "cart-1",
        "cart_fingerprint": FINGERPRINT,
    }
    payload.update(updates)
    return CartSnapshot.model_validate(payload)


def decision(**updates: object) -> DecisionResult:
    payload: dict[str, object] = {
        "decision_id": "precheckout-decision-1",
        "decision": Decision.APPROVE,
        "mandate_id": "mandate-1",
        "mandate_version": 1,
        "candidate_id": "candidate-sony-black",
        "cart_id": "cart-1",
        "cart_fingerprint": FINGERPRINT,
        "approval_requirement": ApprovalRequirement.NONE,
        "evaluated_at": NOW,
    }
    payload.update(updates)
    return DecisionResult.model_validate(payload)


def test_exact_approved_cart_executes_in_sandbox() -> None:
    executor = InMemorySandboxExecutor()

    outcome = executor.execute(
        cart(), decision(), occurred_at=EXECUTION_TIME
    )

    assert outcome.status is TransactionOutcomeStatus.EXECUTED
    assert outcome.transaction_id == (
        "sandbox:cart-1:precheckout-decision-1"
    )
    assert outcome.reason is None
    assert executor.ledger == (outcome,)


@pytest.mark.parametrize("rejected_decision", [Decision.REVIEW, Decision.BLOCK])
def test_review_and_block_never_execute(rejected_decision: Decision) -> None:
    executor = InMemorySandboxExecutor()

    outcome = executor.execute(
        cart(),
        decision(decision=rejected_decision),
        occurred_at=EXECUTION_TIME,
    )

    assert outcome.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert outcome.transaction_id is None
    assert outcome.reason == DECISION_NOT_APPROVED


def test_unresolved_human_approval_never_executes() -> None:
    outcome = execute_sandbox(
        cart(),
        decision(approval_requirement=ApprovalRequirement.HUMAN),
        occurred_at=EXECUTION_TIME,
    )

    assert outcome.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert outcome.reason == HUMAN_APPROVAL_UNRESOLVED


def test_approve_with_recorded_violation_never_executes() -> None:
    recorded_violation = Violation(
        code="TEST_VIOLATION",
        message="The decision is internally inconsistent.",
    )

    outcome = execute_sandbox(
        cart(),
        decision(violations=[recorded_violation]),
        occurred_at=EXECUTION_TIME,
    )

    assert outcome.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert outcome.reason == DECISION_HAS_VIOLATIONS


@pytest.mark.parametrize(
    ("decision_updates", "expected_reason"),
    [
        ({"cart_id": "other-cart"}, DECISION_CART_ID_MISMATCH),
        (
            {"cart_fingerprint": "b" * 64},
            DECISION_CART_FINGERPRINT_MISMATCH,
        ),
        (
            {"candidate_id": "other-candidate"},
            DECISION_CANDIDATE_MISMATCH,
        ),
    ],
)
def test_decision_must_bind_to_exact_cart(
    decision_updates: dict[str, object], expected_reason: str
) -> None:
    outcome = execute_sandbox(
        cart(),
        decision(**decision_updates),
        occurred_at=EXECUTION_TIME,
    )

    assert outcome.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert outcome.reason == expected_reason


def test_future_dated_decision_never_executes() -> None:
    outcome = execute_sandbox(
        cart(),
        decision(evaluated_at=EXECUTION_TIME + timedelta(seconds=1)),
        occurred_at=EXECUTION_TIME,
    )

    assert outcome.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert outcome.reason == DECISION_FROM_FUTURE


def test_identical_retry_is_idempotent() -> None:
    executor = InMemorySandboxExecutor()
    final_cart = cart()
    approved = decision()

    first = executor.execute(
        final_cart, approved, occurred_at=EXECUTION_TIME
    )
    second = executor.execute(
        final_cart,
        approved,
        occurred_at=EXECUTION_TIME + timedelta(minutes=1),
    )

    assert second is first
    assert len(executor.ledger) == 1


def test_reusing_executed_cart_with_different_decision_is_rejected() -> None:
    executor = InMemorySandboxExecutor()
    final_cart = cart()
    executor.execute(final_cart, decision(), occurred_at=EXECUTION_TIME)

    second = executor.execute(
        final_cart,
        decision(decision_id="precheckout-decision-2"),
        occurred_at=EXECUTION_TIME + timedelta(minutes=1),
    )

    assert second.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert second.reason == CART_ALREADY_EXECUTED
    assert len(executor.ledger) == 2


def test_same_decision_id_with_changed_decision_is_not_an_idempotent_retry() -> None:
    executor = InMemorySandboxExecutor()
    final_cart = cart()
    executor.execute(final_cart, decision(), occurred_at=EXECUTION_TIME)

    changed = executor.execute(
        final_cart,
        decision(warnings=["Decision payload changed after execution."]),
        occurred_at=EXECUTION_TIME + timedelta(minutes=1),
    )

    assert changed.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert changed.reason == CART_ALREADY_EXECUTED
    assert len(executor.ledger) == 2


def test_rejected_attempt_does_not_consume_cart_id() -> None:
    executor = InMemorySandboxExecutor()
    final_cart = cart()

    rejected = executor.execute(
        final_cart,
        decision(decision=Decision.REVIEW),
        occurred_at=EXECUTION_TIME,
    )
    executed = executor.execute(
        final_cart,
        decision(decision_id="approved-after-review"),
        occurred_at=EXECUTION_TIME + timedelta(minutes=1),
    )

    assert rejected.status is TransactionOutcomeStatus.NOT_EXECUTED
    assert executed.status is TransactionOutcomeStatus.EXECUTED
    assert len(executor.ledger) == 2


def test_convenience_function_can_share_executor_ledger() -> None:
    executor = InMemorySandboxExecutor()

    outcome = execute_sandbox(
        cart(),
        decision(),
        executor=executor,
        occurred_at=EXECUTION_TIME,
        outcome_id="outcome-custom",
        transaction_id="transaction-custom",
    )

    assert outcome.outcome_id == "outcome-custom"
    assert outcome.transaction_id == "transaction-custom"
    assert executor.ledger == (outcome,)


def test_outcome_round_trips_through_shared_contract() -> None:
    outcome = execute_sandbox(
        cart(), decision(), occurred_at=EXECUTION_TIME
    )

    assert TransactionOutcome.model_validate_json(outcome.model_dump_json()) == outcome
