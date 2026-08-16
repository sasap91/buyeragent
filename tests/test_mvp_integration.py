from __future__ import annotations

from typing import Any

import pytest

from examples.mvp_demo import run_demo


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    return run_demo()


def test_same_catalog_ranks_different_products_for_two_buyers(
    result: dict[str, Any],
) -> None:
    ranking = result["buyer_specific_ranking"]

    assert ranking["maya_top_candidate"] != (
        ranking["existing_buyer_top_candidate"]
    )
    assert ranking["existing_buyer_id"] == "synthetic_household"
    assert ranking["existing_buyer_profile_category"] == "*"
    assert ranking["existing_buyer_top_candidate"] == (
        "catalog-sony-ult-wear-gray"
    )


def test_blocked_candidate_produces_a_successful_replan(
    result: dict[str, Any],
) -> None:
    replan = result["blocked_and_replanned"]

    assert replan["initial_decision"] == "BLOCK"
    assert "ALLOWED_CONDITION_FAIL" in replan["reason_codes"]
    assert replan["blocked_candidate"] in replan["excluded_candidate_ids"]
    assert replan["selected_candidate"] != replan["blocked_candidate"]
    assert replan["selected_decision"] == "APPROVE"


def test_approved_replanned_cart_executes_in_the_sandbox(
    result: dict[str, Any],
) -> None:
    checkout = result["autonomous_checkout"]

    assert checkout["precheckout_decision"] == "APPROVE"
    assert checkout["outcome"] == "EXECUTED"
    assert checkout["transaction_id"] == "sandbox-transaction-autonomous"


def test_exact_cart_human_approval_resolves_spend_review(
    result: dict[str, Any],
) -> None:
    approval = result["human_approval"]

    assert approval["before_approval"] == "REVIEW"
    assert approval["after_approval"] == "APPROVE"
    assert "HUMAN_APPROVAL_APPLIED" in approval["warning_codes"]
    assert approval["outcome"] == "EXECUTED"


def test_material_cart_change_is_caught_before_checkout(
    result: dict[str, Any],
) -> None:
    changed = result["changed_cart"]

    assert changed["decision"] == "REVIEW"
    assert "CART_FINGERPRINT_MISMATCH" in changed["warning_codes"]
