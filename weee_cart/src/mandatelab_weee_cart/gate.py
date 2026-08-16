"""The Decision Engine gate in front of the cart.

Basket suggestions are preferences, not permission. Every line is converted into
a `TransactionCandidate` and run through `parse_mandate` -> `evaluate_candidate`
before the executor is allowed to see it. Only APPROVE passes; REVIEW and BLOCK
are returned with their reasons so the UI can show what was withheld and why.

This is the whole point of MandateLab: the thing that fills the cart does not
get to decide what may go in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from mandatelab_contracts import (
    AuthorizationPolicy,
    Decision,
    Money,
    PurchaseIntent,
    TransactionCandidate,
)
from mandatelab_engine import evaluate_candidate, parse_mandate

# Default spending authority for an unattended weekly grocery run. Anything
# above the autonomous limit escalates to REVIEW rather than being added.
DEFAULT_AUTONOMOUS_LIMIT = Decimal("75.00")
DEFAULT_MAXIMUM_TOTAL = Decimal("150.00")


@dataclass
class GatedLine:
    item: str
    quantity: float
    expected_price: float
    approved: bool
    decision: str
    reason: str
    violations: list[str]
    search_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "quantity": self.quantity,
            "expected_price": self.expected_price,
            "search_query": self.search_query,
            "approved": self.approved,
            "decision": self.decision,
            "reason": self.reason,
            "violations": self.violations,
        }


def _authorization(
    autonomous: Decimal = DEFAULT_AUTONOMOUS_LIMIT,
    maximum: Decimal = DEFAULT_MAXIMUM_TOTAL,
) -> AuthorizationPolicy:
    return AuthorizationPolicy(
        autonomous_spend_limit=Money(amount=autonomous),
        maximum_authorized_total=Money(amount=maximum),
        substitution_allowed=False,
    )


def gate_basket(
    basket,
    profile,
    *,
    autonomous_limit: Decimal = DEFAULT_AUTONOMOUS_LIMIT,
    maximum_total: Decimal = DEFAULT_MAXIMUM_TOTAL,
    now: datetime | None = None,
) -> list[GatedLine]:
    """Run every basket line through the Decision Engine.

    `basket` is a `WeeklyBasket`; `profile` is a shared `BuyerPreferenceProfile`
    (use `buyer_history.contract.to_contract_profile`).
    """
    now = now or datetime.now(UTC)

    intent = PurchaseIntent(
        intent_id=f"weekly-basket-{basket.as_of.isoformat()}",
        buyer_id=basket.buyer_id,
        raw_text=(
            f"Restock the weekly grocery basket for the week of "
            f"{basket.as_of.isoformat()}."
        ),
        goal="Restock recurring household staples",
        category=profile.category,
        authorization=_authorization(autonomous_limit, maximum_total),
        created_at=now,
    )
    mandate = parse_mandate(intent, profile)

    gated: list[GatedLine] = []
    for suggestion in basket.suggestions:
        total = Decimal(str(round(suggestion.estimated_line_total, 2)))
        candidate = TransactionCandidate(
            candidate_id=f"weee:{suggestion.item}",
            product_id=f"weee:{suggestion.item.lower().replace(' ', '-')}",
            product_name=suggestion.item,
            brand=suggestion.brand or None,
            merchant="Weee!",
            item_price=Money(amount=total),
            final_landed_price=Money(amount=total),
            observed_at=now,
        )
        result = evaluate_candidate(candidate, mandate)

        violations = [
            getattr(v, "code", str(v)) for v in getattr(result, "violations", []) or []
        ]
        warnings = list(getattr(result, "warnings", []) or [])
        decision = result.decision

        if decision is Decision.APPROVE:
            reason = "approved within autonomous authority"
        elif decision is Decision.REVIEW:
            reason = "; ".join(warnings) or "needs human approval before it can be added"
        else:
            reason = "; ".join(violations) or "blocked by the mandate"

        gated.append(
            GatedLine(
                item=suggestion.item,
                quantity=suggestion.quantity,
                expected_price=suggestion.estimated_unit_price,
                search_query=getattr(suggestion, 'search_query', '') or suggestion.item,
                approved=decision is Decision.APPROVE,
                decision=decision.value,
                reason=reason,
                violations=violations,
            )
        )

    return gated


def approved_lines(gated: list[GatedLine]) -> list[dict[str, Any]]:
    """Shape the gated lines for `WeeeCartExecutor.add_lines`."""
    return [
        {
            "item": line.item,
            "quantity": line.quantity,
            "expected_price": line.expected_price,
            "search_query": line.search_query or line.item,
            "approved": line.approved,
            "reason": line.reason,
        }
        for line in gated
    ]
