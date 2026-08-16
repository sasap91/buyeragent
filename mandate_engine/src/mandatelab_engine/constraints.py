from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TypeGuard

from mandatelab_contracts import (
    ConstraintKind,
    ConstraintOperator,
    ConstraintResult,
    ConstraintStatus,
    HardConstraint,
    Money,
    TransactionCandidate,
)


class ConstraintDefinitionError(ValueError):
    """Raised when a mandate uses an invalid kind/operator/value combination."""


_OPERATORS_BY_KIND = {
    ConstraintKind.MAX_LANDED_PRICE: ConstraintOperator.LTE,
    ConstraintKind.ALLOWED_CONDITION: ConstraintOperator.IN,
    ConstraintKind.REQUIRED_FEATURES: ConstraintOperator.CONTAINS_ALL,
    ConstraintKind.DELIVERY_BY: ConstraintOperator.ON_OR_BEFORE,
    ConstraintKind.ALLOWED_MERCHANT: ConstraintOperator.IN,
    ConstraintKind.PRODUCT_ID: ConstraintOperator.EQ,
    ConstraintKind.VARIANT_ID: ConstraintOperator.EQ,
}


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _normalized(value: str) -> str:
    return value.strip().casefold()


def _validate_definition(constraint: HardConstraint) -> None:
    expected_operator = _OPERATORS_BY_KIND[constraint.kind]
    if constraint.operator is not expected_operator:
        raise ConstraintDefinitionError(
            f"constraint {constraint.constraint_id!r}: {constraint.kind.value} "
            f"requires operator {expected_operator.value}, got "
            f"{constraint.operator.value}"
        )

    expected = constraint.expected
    valid_expected = {
        ConstraintKind.MAX_LANDED_PRICE: isinstance(expected, Money),
        ConstraintKind.ALLOWED_CONDITION: _is_string_list(expected),
        ConstraintKind.REQUIRED_FEATURES: _is_string_list(expected),
        ConstraintKind.DELIVERY_BY: isinstance(expected, date),
        ConstraintKind.ALLOWED_MERCHANT: _is_string_list(expected),
        ConstraintKind.PRODUCT_ID: isinstance(expected, str),
        ConstraintKind.VARIANT_ID: isinstance(expected, str),
    }[constraint.kind]
    if not valid_expected:
        raise ConstraintDefinitionError(
            f"constraint {constraint.constraint_id!r}: invalid expected value "
            f"for {constraint.kind.value}"
        )


def _result(
    constraint: HardConstraint,
    status: ConstraintStatus,
    actual: Money | date | list[str] | str | None,
    explanation: str,
) -> ConstraintResult:
    return ConstraintResult(
        constraint_id=constraint.constraint_id,
        status=status,
        expected=constraint.expected,
        actual=actual,
        code=f"{constraint.kind.value}_{status.value}",
        explanation=explanation,
    )


def evaluate_constraint(
    constraint: HardConstraint,
    candidate: TransactionCandidate,
) -> ConstraintResult:
    """Evaluate one supported hard constraint using deterministic comparisons."""

    _validate_definition(constraint)

    kind = constraint.kind
    expected = constraint.expected

    if kind is ConstraintKind.MAX_LANDED_PRICE:
        actual = candidate.final_landed_price
        if actual is None:
            return _result(
                constraint,
                ConstraintStatus.UNKNOWN,
                None,
                "Final landed price is missing, so the maximum price cannot be verified.",
            )
        assert isinstance(expected, Money)
        passed = actual.amount <= expected.amount
        return _result(
            constraint,
            ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            actual,
            "Final landed price is within the allowed maximum."
            if passed
            else "Final landed price exceeds the allowed maximum.",
        )

    if kind is ConstraintKind.ALLOWED_CONDITION:
        actual_condition = candidate.condition
        if actual_condition is None:
            return _result(
                constraint,
                ConstraintStatus.UNKNOWN,
                None,
                "Product condition is missing, so allowed condition cannot be verified.",
            )
        assert _is_string_list(expected)
        actual = actual_condition.value
        passed = _normalized(actual) in {_normalized(item) for item in expected}
        return _result(
            constraint,
            ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            actual,
            "Product condition is allowed."
            if passed
            else "Product condition is not allowed.",
        )

    if kind is ConstraintKind.REQUIRED_FEATURES:
        actual = candidate.features
        if actual is None:
            return _result(
                constraint,
                ConstraintStatus.UNKNOWN,
                None,
                "Product features are missing, so required features cannot be verified.",
            )
        assert _is_string_list(expected)
        normalized_actual = {_normalized(item) for item in actual}
        passed = all(_normalized(item) in normalized_actual for item in expected)
        return _result(
            constraint,
            ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            actual,
            "All required features are present."
            if passed
            else "One or more required features are missing.",
        )

    if kind is ConstraintKind.DELIVERY_BY:
        actual = candidate.delivery_date
        if actual is None:
            return _result(
                constraint,
                ConstraintStatus.UNKNOWN,
                None,
                "Delivery date is missing, so the deadline cannot be verified.",
            )
        assert isinstance(expected, date)
        passed = actual <= expected
        return _result(
            constraint,
            ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            actual,
            "Delivery date meets the deadline."
            if passed
            else "Delivery date is after the deadline.",
        )

    if kind is ConstraintKind.ALLOWED_MERCHANT:
        actual = candidate.merchant
        if actual is None:
            return _result(
                constraint,
                ConstraintStatus.UNKNOWN,
                None,
                "Merchant is missing, so the allowed merchant rule cannot be verified.",
            )
        assert _is_string_list(expected)
        passed = _normalized(actual) in {_normalized(item) for item in expected}
        return _result(
            constraint,
            ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            actual,
            "Merchant is allowed." if passed else "Merchant is not allowed.",
        )

    if kind is ConstraintKind.PRODUCT_ID:
        actual = candidate.product_id
        assert isinstance(expected, str)
        passed = actual == expected
        return _result(
            constraint,
            ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
            actual,
            "Product identifier matches."
            if passed
            else "Product identifier does not match.",
        )

    actual = candidate.variant_id
    if actual is None:
        return _result(
            constraint,
            ConstraintStatus.UNKNOWN,
            None,
            "Variant identifier is missing, so the required variant cannot be verified.",
        )
    assert kind is ConstraintKind.VARIANT_ID
    assert isinstance(expected, str)
    passed = actual == expected
    return _result(
        constraint,
        ConstraintStatus.PASS if passed else ConstraintStatus.FAIL,
        actual,
        "Variant identifier matches."
        if passed
        else "Variant identifier does not match.",
    )


def evaluate_constraints(
    constraints: Iterable[HardConstraint],
    candidate: TransactionCandidate,
) -> list[ConstraintResult]:
    """Evaluate constraints in input order without applying decision policy."""

    return [evaluate_constraint(constraint, candidate) for constraint in constraints]


def is_feasible(results: Iterable[ConstraintResult]) -> bool:
    """Return true when every supplied constraint result passes."""

    return all(result.status is ConstraintStatus.PASS for result in results)
