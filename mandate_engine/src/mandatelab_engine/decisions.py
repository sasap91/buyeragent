from __future__ import annotations

from datetime import datetime

from mandatelab_contracts import (
    ApprovalRequirement,
    CartSnapshot,
    ConstraintResult,
    ConstraintStatus,
    Decision,
    DecisionResult,
    HardConstraint,
    Mandate,
    ReplanInstruction,
    TransactionCandidate,
    Violation,
)

from mandatelab_engine.constraints import evaluate_constraints


MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED = "MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED"
AUTONOMOUS_SPEND_LIMIT_EXCEEDED = "AUTONOMOUS_SPEND_LIMIT_EXCEEDED"
FINAL_LANDED_PRICE_UNKNOWN = "FINAL_LANDED_PRICE_UNKNOWN"
MATERIAL_AMBIGUITY = "MATERIAL_AMBIGUITY"


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _constraint_violation(result: ConstraintResult) -> Violation:
    return Violation(
        code=result.code,
        message=result.explanation,
        constraint_id=result.constraint_id,
        expected=result.expected,
        actual=result.actual,
    )


def _replan(
    candidate: TransactionCandidate,
    violations: list[Violation],
    failed_constraints: list[HardConstraint],
) -> ReplanInstruction:
    reason_codes = _deduplicate([violation.code for violation in violations])
    if MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED in reason_codes:
        message = (
            "Exclude this candidate and search again for an option that satisfies "
            "the mandate and remains within the maximum authorized total."
        )
    else:
        message = (
            "Exclude this candidate and search again for an option that satisfies "
            "the failed mandate constraints."
        )
    return ReplanInstruction(
        reason_codes=reason_codes,
        required_constraints=failed_constraints,
        exclude_candidate_ids=[candidate.candidate_id],
        message=message,
    )


def evaluate_candidate(
    candidate: TransactionCandidate,
    mandate: Mandate,
    *,
    decision_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> DecisionResult:
    """Return a deterministic authorization decision for one candidate."""

    constraint_results = evaluate_constraints(
        mandate.hard_constraints, candidate
    )
    evaluated_constraints = list(
        zip(mandate.hard_constraints, constraint_results, strict=True)
    )

    failed_constraints = [
        constraint
        for constraint, result in evaluated_constraints
        if result.status is ConstraintStatus.FAIL
    ]
    required_unknowns = [
        result
        for constraint, result in evaluated_constraints
        if constraint.required and result.status is ConstraintStatus.UNKNOWN
    ]
    violations = [
        _constraint_violation(result)
        for _, result in evaluated_constraints
        if result.status is ConstraintStatus.FAIL
    ]
    unknown_results = [
        result
        for _, result in evaluated_constraints
        if result.status is ConstraintStatus.UNKNOWN
    ]
    warnings = [
        f"{result.code}: {result.explanation}"
        for result in unknown_results
    ]

    final_price = candidate.final_landed_price
    over_maximum = False
    over_autonomous = False
    if final_price is None:
        warnings.append(
            f"{FINAL_LANDED_PRICE_UNKNOWN}: Final landed price is required "
            "for authorization."
        )
    else:
        over_maximum = (
            final_price.amount
            > mandate.authorization.maximum_authorized_total.amount
        )
        over_autonomous = (
            final_price.amount
            > mandate.authorization.autonomous_spend_limit.amount
        )

        if over_maximum:
            violations.append(
                Violation(
                    code=MAXIMUM_AUTHORIZED_TOTAL_EXCEEDED,
                    message=(
                        "Final landed price exceeds the maximum total authorized "
                        "by the buyer."
                    ),
                    expected=mandate.authorization.maximum_authorized_total,
                    actual=final_price,
                )
            )
        elif over_autonomous:
            warnings.append(
                f"{AUTONOMOUS_SPEND_LIMIT_EXCEEDED}: Final landed price "
                "requires human approval."
            )

    warnings.extend(
        f"{MATERIAL_AMBIGUITY}: {ambiguity}"
        for ambiguity in mandate.material_ambiguities
    )
    warnings = _deduplicate(warnings)

    should_block = bool(failed_constraints) or over_maximum
    should_review = (
        bool(required_unknowns)
        or final_price is None
        or bool(mandate.material_ambiguities)
        or over_autonomous
    )

    if should_block:
        decision = Decision.BLOCK
        approval_requirement = ApprovalRequirement.NONE
        replan_instruction = _replan(
            candidate, violations, failed_constraints
        )
    elif should_review:
        decision = Decision.REVIEW
        approval_requirement = ApprovalRequirement.HUMAN
        replan_instruction = None
    else:
        decision = Decision.APPROVE
        approval_requirement = ApprovalRequirement.NONE
        replan_instruction = None

    cart_id = None
    cart_fingerprint = None
    if isinstance(candidate, CartSnapshot):
        cart_id = candidate.cart_id
        cart_fingerprint = candidate.cart_fingerprint

    return DecisionResult(
        decision_id=(
            decision_id
            or f"decision:{mandate.mandate_id}:{mandate.version}:"
            f"{candidate.candidate_id}"
        ),
        decision=decision,
        mandate_id=mandate.mandate_id,
        mandate_version=mandate.version,
        candidate_id=candidate.candidate_id,
        cart_id=cart_id,
        cart_fingerprint=cart_fingerprint,
        constraint_results=constraint_results,
        violations=violations,
        warnings=warnings,
        approval_requirement=approval_requirement,
        replan_instruction=replan_instruction,
        evaluated_at=evaluated_at or candidate.observed_at,
    )
