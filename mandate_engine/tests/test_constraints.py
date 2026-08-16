from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from mandatelab_contracts import (
    BuyerPreferenceProfile,
    ConstraintKind,
    ConstraintOperator,
    ConstraintStatus,
    HardConstraint,
    MandateSource,
    Money,
    ProductCondition,
    TransactionCandidate,
)
from mandatelab_engine import (
    ConstraintDefinitionError,
    evaluate_constraint,
    evaluate_constraints,
    is_feasible,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)


def candidate(**updates: object) -> TransactionCandidate:
    values: dict[str, object] = {
        "candidate_id": "candidate-sony-black",
        "product_id": "sony-wh-1000xm5",
        "variant_id": "black",
        "product_name": "Sony WH-1000XM5",
        "brand": "Sony",
        "condition": ProductCondition.NEW,
        "features": ["active-noise-cancelling", "bluetooth", "multipoint"],
        "merchant": "MandateMart",
        "item_price": Money(amount="229.99"),
        "shipping": Money(amount="0"),
        "fees": Money(amount="0"),
        "final_landed_price": Money(amount="229.99"),
        "delivery_date": date(2026, 8, 19),
        "observed_at": NOW,
    }
    values.update(updates)
    return TransactionCandidate.model_validate(values)


def constraint(
    kind: ConstraintKind,
    operator: ConstraintOperator,
    expected: object,
) -> HardConstraint:
    return HardConstraint.model_validate(
        {
            "constraint_id": f"test-{kind.value.lower()}",
            "kind": kind,
            "operator": operator,
            "expected": expected,
            "source": MandateSource.CURRENT_EXPLICIT,
        }
    )


@pytest.mark.parametrize(
    ("kind", "operator", "expected", "candidate_updates"),
    [
        (
            ConstraintKind.MAX_LANDED_PRICE,
            ConstraintOperator.LTE,
            Money(amount="230"),
            {},
        ),
        (
            ConstraintKind.ALLOWED_CONDITION,
            ConstraintOperator.IN,
            ["new"],
            {},
        ),
        (
            ConstraintKind.REQUIRED_FEATURES,
            ConstraintOperator.CONTAINS_ALL,
            ["Bluetooth", "ACTIVE-NOISE-CANCELLING"],
            {},
        ),
        (
            ConstraintKind.DELIVERY_BY,
            ConstraintOperator.ON_OR_BEFORE,
            date(2026, 8, 19),
            {},
        ),
        (
            ConstraintKind.ALLOWED_MERCHANT,
            ConstraintOperator.IN,
            ["mandatemart"],
            {},
        ),
        (
            ConstraintKind.PRODUCT_ID,
            ConstraintOperator.EQ,
            "sony-wh-1000xm5",
            {},
        ),
        (
            ConstraintKind.VARIANT_ID,
            ConstraintOperator.EQ,
            "black",
            {},
        ),
    ],
)
def test_supported_constraints_pass(
    kind: ConstraintKind,
    operator: ConstraintOperator,
    expected: object,
    candidate_updates: dict[str, object],
) -> None:
    result = evaluate_constraint(
        constraint(kind, operator, expected), candidate(**candidate_updates)
    )

    assert result.status is ConstraintStatus.PASS
    assert result.code == f"{kind.value}_PASS"


@pytest.mark.parametrize(
    ("kind", "operator", "expected", "candidate_updates"),
    [
        (
            ConstraintKind.MAX_LANDED_PRICE,
            ConstraintOperator.LTE,
            Money(amount="200"),
            {},
        ),
        (
            ConstraintKind.ALLOWED_CONDITION,
            ConstraintOperator.IN,
            ["REFURBISHED"],
            {},
        ),
        (
            ConstraintKind.REQUIRED_FEATURES,
            ConstraintOperator.CONTAINS_ALL,
            ["spatial-audio"],
            {},
        ),
        (
            ConstraintKind.DELIVERY_BY,
            ConstraintOperator.ON_OR_BEFORE,
            date(2026, 8, 18),
            {},
        ),
        (
            ConstraintKind.ALLOWED_MERCHANT,
            ConstraintOperator.IN,
            ["Other Store"],
            {},
        ),
        (
            ConstraintKind.PRODUCT_ID,
            ConstraintOperator.EQ,
            "bose-quietcomfort",
            {},
        ),
        (
            ConstraintKind.VARIANT_ID,
            ConstraintOperator.EQ,
            "silver",
            {},
        ),
    ],
)
def test_supported_constraints_fail(
    kind: ConstraintKind,
    operator: ConstraintOperator,
    expected: object,
    candidate_updates: dict[str, object],
) -> None:
    result = evaluate_constraint(
        constraint(kind, operator, expected), candidate(**candidate_updates)
    )

    assert result.status is ConstraintStatus.FAIL
    assert result.code == f"{kind.value}_FAIL"


@pytest.mark.parametrize(
    ("kind", "operator", "expected", "missing_field"),
    [
        (
            ConstraintKind.MAX_LANDED_PRICE,
            ConstraintOperator.LTE,
            Money(amount="250"),
            "final_landed_price",
        ),
        (
            ConstraintKind.ALLOWED_CONDITION,
            ConstraintOperator.IN,
            ["NEW"],
            "condition",
        ),
        (
            ConstraintKind.REQUIRED_FEATURES,
            ConstraintOperator.CONTAINS_ALL,
            ["bluetooth"],
            "features",
        ),
        (
            ConstraintKind.DELIVERY_BY,
            ConstraintOperator.ON_OR_BEFORE,
            date(2026, 8, 20),
            "delivery_date",
        ),
        (
            ConstraintKind.ALLOWED_MERCHANT,
            ConstraintOperator.IN,
            ["MandateMart"],
            "merchant",
        ),
        (
            ConstraintKind.VARIANT_ID,
            ConstraintOperator.EQ,
            "black",
            "variant_id",
        ),
    ],
)
def test_missing_constraint_data_is_unknown(
    kind: ConstraintKind,
    operator: ConstraintOperator,
    expected: object,
    missing_field: str,
) -> None:
    result = evaluate_constraint(
        constraint(kind, operator, expected), candidate(**{missing_field: None})
    )

    assert result.status is ConstraintStatus.UNKNOWN
    assert result.actual is None
    assert result.code == f"{kind.value}_UNKNOWN"


def test_invalid_operator_is_rejected_as_a_mandate_definition_error() -> None:
    malformed = constraint(
        ConstraintKind.MAX_LANDED_PRICE,
        ConstraintOperator.EQ,
        Money(amount="250"),
    )

    with pytest.raises(ConstraintDefinitionError, match="requires operator LTE"):
        evaluate_constraint(malformed, candidate())


def test_invalid_expected_value_is_rejected_as_a_definition_error() -> None:
    malformed = constraint(
        ConstraintKind.MAX_LANDED_PRICE,
        ConstraintOperator.LTE,
        "not-money",
    )

    with pytest.raises(ConstraintDefinitionError, match="invalid expected value"):
        evaluate_constraint(malformed, candidate())


def test_batch_evaluation_preserves_order_and_feasibility_requires_no_unknowns() -> None:
    rules = [
        constraint(
            ConstraintKind.MAX_LANDED_PRICE,
            ConstraintOperator.LTE,
            Money(amount="250"),
        ),
        constraint(
            ConstraintKind.ALLOWED_CONDITION,
            ConstraintOperator.IN,
            ["NEW"],
        ),
    ]

    passing = evaluate_constraints(rules, candidate())
    uncertain = evaluate_constraints(rules, candidate(condition=None))

    assert [result.constraint_id for result in passing] == [
        rule.constraint_id for rule in rules
    ]
    assert is_feasible(passing) is True
    assert is_feasible(uncertain) is False
    assert is_feasible([]) is True


def test_headphone_catalog_contains_twelve_valid_normalized_candidates() -> None:
    payload = json.loads(
        (FIXTURES / "headphones_catalog.json").read_text(encoding="utf-8")
    )
    candidates = [
        TransactionCandidate.model_validate(item) for item in payload["candidates"]
    ]

    assert payload["category"] == "headphones"
    assert len(candidates) == 12
    assert len({item.candidate_id for item in candidates}) == len(candidates)
    assert candidates[-1].final_landed_price is None


def test_existing_buyer_fixture_uses_history_sources() -> None:
    profile = BuyerPreferenceProfile.model_validate_json(
        (FIXTURES / "existing_buyer_profile.json").read_text(encoding="utf-8")
    )

    assert profile.buyer_id == "buyer-theo"
    assert profile.price_sensitivity.source.value == "CATEGORY_HISTORY"
    assert profile.price_sensitivity.confidence > 0
