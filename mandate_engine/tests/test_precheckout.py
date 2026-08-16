from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from mandatelab_contracts import (
    ApprovalRequirement,
    AuthorizationPolicy,
    CartSnapshot,
    ConstraintKind,
    ConstraintOperator,
    Decision,
    DecisionResult,
    HardConstraint,
    HumanApproval,
    Mandate,
    MandateSource,
    MaterialCartField,
    Money,
    ProductCondition,
    TransactionCandidate,
)
from mandatelab_engine import (
    APPROVAL_CANNOT_OVERRIDE_REVIEW,
    APPROVAL_CART_MISMATCH,
    APPROVAL_EXPIRED,
    APPROVAL_FINGERPRINT_MISMATCH,
    APPROVAL_MANDATE_MISMATCH,
    APPROVAL_MANDATE_VERSION_MISMATCH,
    APPROVAL_NOT_YET_VALID,
    APPROVAL_REQUIRED,
    CART_FINGERPRINT_MISMATCH,
    HUMAN_APPROVAL_APPLIED,
    compute_cart_fingerprint,
    validate_precheckout,
)


NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)
CHECKOUT_TIME = NOW + timedelta(hours=1)


def authorization(
    autonomous: str = "200",
    maximum: str = "250",
    material_fields: list[MaterialCartField] | None = None,
) -> AuthorizationPolicy:
    payload: dict[str, object] = {
        "autonomous_spend_limit": Money(amount=autonomous),
        "maximum_authorized_total": Money(amount=maximum),
    }
    if material_fields is not None:
        payload["material_change_fields"] = material_fields
    return AuthorizationPolicy.model_validate(payload)


def mandate(**updates: object) -> Mandate:
    payload: dict[str, object] = {
        "mandate_id": "mandate-headphones-1",
        "version": 1,
        "buyer_id": "buyer-maya",
        "goal": "Buy noise-cancelling headphones",
        "category": "headphones",
        "authorization": authorization(),
        "created_at": NOW,
    }
    payload.update(updates)
    return Mandate.model_validate(payload)


def candidate(**updates: object) -> TransactionCandidate:
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
        "delivery_date": date(2026, 8, 19),
        "observed_at": NOW,
    }
    payload.update(updates)
    return TransactionCandidate.model_validate(payload)


def cart(for_mandate: Mandate, **updates: object) -> CartSnapshot:
    transaction_candidate = candidate(**updates)
    fingerprint = compute_cart_fingerprint(
        transaction_candidate,
        for_mandate.authorization.material_change_fields,
    )
    return CartSnapshot(
        **transaction_candidate.model_dump(),
        cart_id="cart-1",
        cart_fingerprint=fingerprint,
    )


def approval(
    for_cart: CartSnapshot,
    for_mandate: Mandate,
    **updates: object,
) -> HumanApproval:
    payload: dict[str, object] = {
        "approval_id": "approval-1",
        "mandate_id": for_mandate.mandate_id,
        "mandate_version": for_mandate.version,
        "cart_id": for_cart.cart_id,
        "cart_fingerprint": for_cart.cart_fingerprint,
        "approver_id": "buyer-maya",
        "approved_at": NOW,
        "expires_at": NOW + timedelta(hours=2),
    }
    payload.update(updates)
    return HumanApproval.model_validate(payload)


def condition_rule() -> HardConstraint:
    return HardConstraint(
        constraint_id="new-only",
        kind=ConstraintKind.ALLOWED_CONDITION,
        operator=ConstraintOperator.IN,
        expected=["NEW"],
        source=MandateSource.CURRENT_EXPLICIT,
    )


def test_fingerprint_is_canonical_for_equivalent_decimal_amounts() -> None:
    policy = authorization()
    first = candidate(final_landed_price=Money(amount="200.00"))
    second = candidate(final_landed_price=Money(amount="2E+2"))

    first_hash = compute_cart_fingerprint(
        first, policy.material_change_fields
    )
    second_hash = compute_cart_fingerprint(
        second, reversed(policy.material_change_fields)
    )

    assert first_hash == second_hash
    assert len(first_hash) == 64


def test_fingerprint_changes_only_for_configured_material_fields() -> None:
    fields = [MaterialCartField.PRODUCT_ID, MaterialCartField.MERCHANT]
    base = candidate()
    changed_price = candidate(final_landed_price=Money(amount="175"))
    changed_merchant = candidate(merchant="Other Store")

    base_hash = compute_cart_fingerprint(base, fields)

    assert compute_cart_fingerprint(changed_price, fields) == base_hash
    assert compute_cart_fingerprint(changed_merchant, fields) != base_hash


def test_valid_autonomous_cart_approves_without_human_approval() -> None:
    active_mandate = mandate(hard_constraints=[condition_rule()])

    result = validate_precheckout(
        cart(active_mandate), active_mandate, evaluated_at=CHECKOUT_TIME
    )

    assert result.decision is Decision.APPROVE
    assert result.approval_requirement is ApprovalRequirement.NONE
    assert result.cart_id == "cart-1"


def test_above_autonomous_limit_requires_exact_cart_approval() -> None:
    active_mandate = mandate()

    result = validate_precheckout(
        cart(active_mandate, final_landed_price=Money(amount="225")),
        active_mandate,
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.REVIEW
    assert result.approval_requirement is ApprovalRequirement.HUMAN
    assert any(warning.startswith(APPROVAL_REQUIRED) for warning in result.warnings)


def test_valid_exact_cart_approval_resolves_autonomous_spend_review() -> None:
    active_mandate = mandate()
    final_cart = cart(
        active_mandate, final_landed_price=Money(amount="225")
    )

    result = validate_precheckout(
        final_cart,
        active_mandate,
        approval(final_cart, active_mandate),
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.APPROVE
    assert result.approval_requirement is ApprovalRequirement.NONE
    assert any(
        warning.startswith(HUMAN_APPROVAL_APPLIED)
        for warning in result.warnings
    )
    assert not any(
        warning.startswith("AUTONOMOUS_SPEND_LIMIT_EXCEEDED")
        for warning in result.warnings
    )


@pytest.mark.parametrize(
    ("approval_updates", "expected_code"),
    [
        ({"mandate_id": "other-mandate"}, APPROVAL_MANDATE_MISMATCH),
        ({"mandate_version": 2}, APPROVAL_MANDATE_VERSION_MISMATCH),
        ({"cart_id": "other-cart"}, APPROVAL_CART_MISMATCH),
        ({"cart_fingerprint": "b" * 64}, APPROVAL_FINGERPRINT_MISMATCH),
        (
            {
                "approved_at": CHECKOUT_TIME + timedelta(minutes=1),
                "expires_at": CHECKOUT_TIME + timedelta(hours=1),
            },
            APPROVAL_NOT_YET_VALID,
        ),
    ],
)
def test_mismatched_or_future_approval_requires_review(
    approval_updates: dict[str, object], expected_code: str
) -> None:
    active_mandate = mandate()
    final_cart = cart(
        active_mandate, final_landed_price=Money(amount="225")
    )
    supplied_approval = approval(
        final_cart, active_mandate, **approval_updates
    )

    result = validate_precheckout(
        final_cart,
        active_mandate,
        supplied_approval,
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.REVIEW
    assert any(warning.startswith(expected_code) for warning in result.warnings)


def test_approval_is_expired_at_its_expiry_instant() -> None:
    active_mandate = mandate()
    final_cart = cart(
        active_mandate, final_landed_price=Money(amount="225")
    )
    supplied_approval = approval(
        final_cart, active_mandate, expires_at=CHECKOUT_TIME
    )

    result = validate_precheckout(
        final_cart,
        active_mandate,
        supplied_approval,
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.REVIEW
    assert any(warning.startswith(APPROVAL_EXPIRED) for warning in result.warnings)


def test_stale_cart_fingerprint_requires_review() -> None:
    active_mandate = mandate()
    original = cart(active_mandate)
    payload = original.model_dump()
    payload["merchant"] = "Other Store"
    stale_cart = CartSnapshot.model_validate(payload)

    result = validate_precheckout(
        stale_cart, active_mandate, evaluated_at=CHECKOUT_TIME
    )

    assert result.decision is Decision.REVIEW
    assert any(
        warning.startswith(CART_FINGERPRINT_MISMATCH)
        for warning in result.warnings
    )


def test_material_cart_change_invalidates_earlier_approval() -> None:
    active_mandate = mandate()
    original = cart(
        active_mandate, final_landed_price=Money(amount="225")
    )
    original_approval = approval(original, active_mandate)
    changed = cart(
        active_mandate,
        final_landed_price=Money(amount="225"),
        merchant="Other Store",
    )

    result = validate_precheckout(
        changed,
        active_mandate,
        original_approval,
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.REVIEW
    assert any(
        warning.startswith(APPROVAL_FINGERPRINT_MISMATCH)
        for warning in result.warnings
    )


def test_human_approval_cannot_override_hard_constraint_failure() -> None:
    active_mandate = mandate(hard_constraints=[condition_rule()])
    final_cart = cart(
        active_mandate,
        condition=ProductCondition.USED,
        final_landed_price=Money(amount="225"),
    )

    result = validate_precheckout(
        final_cart,
        active_mandate,
        approval(final_cart, active_mandate),
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.BLOCK
    assert result.violations[0].code == "ALLOWED_CONDITION_FAIL"


@pytest.mark.parametrize(
    "mandate_updates,cart_updates",
    [
        ({"hard_constraints": [condition_rule()]}, {"condition": None}),
        ({"material_ambiguities": ["COLOR_NOT_SPECIFIED"]}, {}),
    ],
)
def test_human_approval_cannot_override_non_spend_review(
    mandate_updates: dict[str, object], cart_updates: dict[str, object]
) -> None:
    active_mandate = mandate(**mandate_updates)
    final_cart = cart(
        active_mandate,
        final_landed_price=Money(amount="225"),
        **cart_updates,
    )

    result = validate_precheckout(
        final_cart,
        active_mandate,
        approval(final_cart, active_mandate),
        evaluated_at=CHECKOUT_TIME,
    )

    assert result.decision is Decision.REVIEW
    assert any(
        warning.startswith(APPROVAL_CANNOT_OVERRIDE_REVIEW)
        for warning in result.warnings
    )


def test_precheckout_result_round_trips_with_deterministic_identity() -> None:
    active_mandate = mandate()
    result = validate_precheckout(
        cart(active_mandate), active_mandate, evaluated_at=CHECKOUT_TIME
    )

    assert result.decision_id == "precheckout:mandate-headphones-1:1:cart-1"
    assert result.evaluated_at == CHECKOUT_TIME
    assert DecisionResult.model_validate_json(result.model_dump_json()) == result
