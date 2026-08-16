from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal

from mandatelab_contracts import (
    ApprovalRequirement,
    CartSnapshot,
    ConstraintStatus,
    Decision,
    DecisionResult,
    HumanApproval,
    Mandate,
    MaterialCartField,
    Money,
    TransactionCandidate,
)

from mandatelab_engine.decisions import (
    AUTONOMOUS_SPEND_LIMIT_EXCEEDED,
    evaluate_candidate,
)


CART_FINGERPRINT_MISMATCH = "CART_FINGERPRINT_MISMATCH"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
APPROVAL_MANDATE_MISMATCH = "APPROVAL_MANDATE_MISMATCH"
APPROVAL_MANDATE_VERSION_MISMATCH = "APPROVAL_MANDATE_VERSION_MISMATCH"
APPROVAL_CART_MISMATCH = "APPROVAL_CART_MISMATCH"
APPROVAL_FINGERPRINT_MISMATCH = "APPROVAL_FINGERPRINT_MISMATCH"
APPROVAL_NOT_YET_VALID = "APPROVAL_NOT_YET_VALID"
APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
APPROVAL_CANNOT_OVERRIDE_REVIEW = "APPROVAL_CANNOT_OVERRIDE_REVIEW"
HUMAN_APPROVAL_APPLIED = "HUMAN_APPROVAL_APPLIED"


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_money(value: Money | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "amount": _canonical_decimal(value.amount),
        "currency": value.currency,
    }


def _material_value(
    candidate: TransactionCandidate, field: MaterialCartField
) -> object:
    if field is MaterialCartField.PRODUCT_ID:
        return candidate.product_id
    if field is MaterialCartField.VARIANT_ID:
        return candidate.variant_id
    if field is MaterialCartField.FINAL_LANDED_PRICE:
        return _canonical_money(candidate.final_landed_price)
    if field is MaterialCartField.CONDITION:
        return candidate.condition.value if candidate.condition is not None else None
    if field is MaterialCartField.MERCHANT:
        return candidate.merchant
    if field is MaterialCartField.DELIVERY_DATE:
        return (
            candidate.delivery_date.isoformat()
            if candidate.delivery_date is not None
            else None
        )
    raise AssertionError(f"unsupported material cart field: {field}")


def compute_cart_fingerprint(
    candidate: TransactionCandidate,
    material_fields: Iterable[MaterialCartField],
) -> str:
    """Hash the configured material fields using a canonical JSON encoding."""

    fields = sorted(set(material_fields), key=lambda field: field.value)
    payload = {
        field.value: _material_value(candidate, field) for field in fields
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approval_issues(
    approval: HumanApproval,
    cart: CartSnapshot,
    mandate: Mandate,
    evaluated_at: datetime,
) -> list[str]:
    issues: list[str] = []
    if approval.mandate_id != mandate.mandate_id:
        issues.append(APPROVAL_MANDATE_MISMATCH)
    if approval.mandate_version != mandate.version:
        issues.append(APPROVAL_MANDATE_VERSION_MISMATCH)
    if approval.cart_id != cart.cart_id:
        issues.append(APPROVAL_CART_MISMATCH)
    if approval.cart_fingerprint != cart.cart_fingerprint:
        issues.append(APPROVAL_FINGERPRINT_MISMATCH)
    if approval.approved_at > evaluated_at:
        issues.append(APPROVAL_NOT_YET_VALID)
    if approval.expires_at is not None and evaluated_at >= approval.expires_at:
        issues.append(APPROVAL_EXPIRED)
    return issues


def _has_non_overridable_review_reason(
    result: DecisionResult, mandate: Mandate, cart: CartSnapshot
) -> bool:
    required_ids = {
        constraint.constraint_id
        for constraint in mandate.hard_constraints
        if constraint.required
    }
    required_unknown = any(
        item.constraint_id in required_ids
        and item.status is ConstraintStatus.UNKNOWN
        for item in result.constraint_results
    )
    return (
        required_unknown
        or cart.final_landed_price is None
        or bool(mandate.material_ambiguities)
    )


def _updated_result(
    result: DecisionResult,
    *,
    decision: Decision | None = None,
    approval_requirement: ApprovalRequirement | None = None,
    warnings: list[str] | None = None,
) -> DecisionResult:
    payload = result.model_dump()
    if decision is not None:
        payload["decision"] = decision
    if approval_requirement is not None:
        payload["approval_requirement"] = approval_requirement
    if warnings is not None:
        payload["warnings"] = list(dict.fromkeys(warnings))
    return DecisionResult.model_validate(payload)


def validate_precheckout(
    cart: CartSnapshot,
    mandate: Mandate,
    approval: HumanApproval | None = None,
    *,
    decision_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> DecisionResult:
    """Revalidate the final cart and any exact-cart human approval."""

    timestamp = evaluated_at or datetime.now(timezone.utc)
    result = evaluate_candidate(
        cart,
        mandate,
        decision_id=(
            decision_id
            or f"precheckout:{mandate.mandate_id}:{mandate.version}:{cart.cart_id}"
        ),
        evaluated_at=timestamp,
    )

    expected_fingerprint = compute_cart_fingerprint(
        cart, mandate.authorization.material_change_fields
    )
    fingerprint_valid = expected_fingerprint == cart.cart_fingerprint
    warnings = list(result.warnings)
    if not fingerprint_valid:
        warnings.append(
            f"{CART_FINGERPRINT_MISMATCH}: Cart material fields do not match "
            "the supplied fingerprint."
        )

    if result.decision is Decision.BLOCK:
        return _updated_result(result, warnings=warnings)

    approval_issues: list[str] = []
    if approval is not None:
        approval_issues = _approval_issues(
            approval, cart, mandate, timestamp
        )
        warnings.extend(f"{code}: Human approval is not valid." for code in approval_issues)

    if not fingerprint_valid or approval_issues:
        return _updated_result(
            result,
            decision=Decision.REVIEW,
            approval_requirement=ApprovalRequirement.HUMAN,
            warnings=warnings,
        )

    if result.decision is Decision.APPROVE:
        return _updated_result(result, warnings=warnings)

    if approval is None:
        if any(
            warning.startswith(AUTONOMOUS_SPEND_LIMIT_EXCEEDED)
            for warning in result.warnings
        ):
            warnings.append(
                f"{APPROVAL_REQUIRED}: Exact-cart human approval is required."
            )
        return _updated_result(result, warnings=warnings)

    if _has_non_overridable_review_reason(result, mandate, cart):
        warnings.append(
            f"{APPROVAL_CANNOT_OVERRIDE_REVIEW}: Approval cannot resolve "
            "missing required data or mandate ambiguity."
        )
        return _updated_result(result, warnings=warnings)

    warnings = [
        warning
        for warning in warnings
        if not warning.startswith(AUTONOMOUS_SPEND_LIMIT_EXCEEDED)
    ]
    warnings.append(
        f"{HUMAN_APPROVAL_APPLIED}: Approval {approval.approval_id} authorizes "
        "this exact cart snapshot."
    )
    return _updated_result(
        result,
        decision=Decision.APPROVE,
        approval_requirement=ApprovalRequirement.NONE,
        warnings=warnings,
    )
