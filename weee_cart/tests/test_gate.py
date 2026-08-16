"""The Decision Engine gate in front of the cart."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from buyer_history import build_profile_from_workbook
from buyer_history.basket import suggest_weekly_basket
from buyer_history.contract import to_contract_profile
from mandatelab_weee_cart import (
    BROWSER_UNAVAILABLE,
    NOT_APPROVED,
    WeeeCartExecutor,
    approved_lines,
    gate_basket,
)

WORKBOOK = "buyer_history/fixtures/synthetic_household.xlsx"
TODAY = date(2026, 8, 16)
DEAD_PORT = "http://127.0.0.1:9"


@pytest.fixture(scope="module")
def basket_and_profile():
    bundle = build_profile_from_workbook(WORKBOOK, buyer_id="household", as_of=TODAY)
    return suggest_weekly_basket(bundle, as_of=TODAY), to_contract_profile(bundle, None)


def test_every_line_gets_a_decision(basket_and_profile) -> None:
    basket, profile = basket_and_profile
    gated = gate_basket(basket, profile)
    assert len(gated) == len(basket.suggestions)
    assert all(g.decision in {"APPROVE", "REVIEW", "BLOCK"} for g in gated)
    assert all(g.reason for g in gated)


def test_a_tight_spend_limit_escalates_rather_than_approving(basket_and_profile) -> None:
    """The gate must have teeth: a low limit has to produce REVIEW."""
    basket, profile = basket_and_profile
    generous = gate_basket(basket, profile)
    tight = gate_basket(
        basket, profile, autonomous_limit=Decimal("2"), maximum_total=Decimal("500")
    )
    assert sum(g.approved for g in tight) < sum(g.approved for g in generous)
    escalated = [g for g in tight if g.decision == "REVIEW"]
    assert escalated
    assert any("AUTONOMOUS_SPEND_LIMIT_EXCEEDED" in g.reason for g in escalated)


def test_unapproved_lines_never_reach_the_browser(basket_and_profile) -> None:
    """The executor refuses without a decision, so it cannot be called around."""
    basket, profile = basket_and_profile
    gated = gate_basket(
        basket, profile, autonomous_limit=Decimal("2"), maximum_total=Decimal("500")
    )
    lines = approved_lines(gated)
    assert any(not line["approved"] for line in lines)

    run = WeeeCartExecutor(cdp_url=DEAD_PORT, dry_run=True).add_lines(lines)
    refused = {r.item for r in run.results if r.status == NOT_APPROVED}
    reached = {r.item for r in run.results if r.status == BROWSER_UNAVAILABLE}
    assert refused
    assert not (refused & reached)


def test_executor_refuses_without_a_browser() -> None:
    run = WeeeCartExecutor(cdp_url=DEAD_PORT, dry_run=False).add_lines(
        [{"item": "Kale", "quantity": 1, "expected_price": 3.19, "approved": True}]
    )
    assert run.error and "No debuggable Chrome" in run.error
    assert run.added == 0


def test_there_is_no_checkout_path() -> None:
    """Adding to a cart is reversible; buying is not. This module only adds."""
    source = Path("weee_cart/src/mandatelab_weee_cart/executor.py").read_text().lower()
    source = source.replace("there is no checkout path in this file", "")
    for forbidden in ("checkout", "place_order", "submit_order"):
        assert forbidden not in source


def test_gated_lines_serialize(basket_and_profile) -> None:
    basket, profile = basket_and_profile
    payload = [g.to_dict() for g in gate_basket(basket, profile)]
    assert all({"item", "decision", "approved", "reason"} <= p.keys() for p in payload)
