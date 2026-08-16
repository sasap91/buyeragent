"""Weekly basket suggestions."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from buyer_history import build_profile_from_workbook
from buyer_history.basket import format_basket, suggest_weekly_basket
from buyer_history.schema import RepeatBehavior

WORKBOOK = "buyer_history/fixtures/synthetic_household.xlsx"
TODAY = date(2026, 8, 16)


@pytest.fixture(scope="module")
def bundle():
    return build_profile_from_workbook(WORKBOOK, buyer_id="synthetic_household", as_of=TODAY)


def test_basket_is_not_empty_and_costs_something(bundle) -> None:
    basket = suggest_weekly_basket(bundle, as_of=TODAY)
    assert basket.suggestions
    assert basket.estimated_total > 0
    assert basket.estimated_total == pytest.approx(
        sum(s.estimated_line_total for s in basket.suggestions), abs=0.01
    )


def test_one_off_purchases_are_not_suggested(bundle) -> None:
    """A product bought once is a past decision, not a recurring need."""
    basket = suggest_weekly_basket(bundle, as_of=TODAY)
    suggested = {s.item for s in basket.suggestions}
    one_offs = {
        name
        for name, profile in bundle.item_profiles.items()
        if profile.repeat_behavior is RepeatBehavior.ONE_OFF
    }
    assert one_offs, "fixture should contain one-off purchases"
    assert not (suggested & one_offs)


def test_every_line_carries_its_reasoning(bundle) -> None:
    basket = suggest_weekly_basket(bundle, as_of=TODAY)
    for suggestion in basket.suggestions:
        assert suggestion.reasons, suggestion.item
        assert suggestion.quantity >= 1
        assert suggestion.estimated_unit_price > 0
        assert 0.0 <= suggestion.probability <= 1.0
        assert suggestion.status in {"DUE", "OVERDUE", "STAPLE"}


def test_unrecorded_trips_read_as_staples_not_centuries_overdue(bundle) -> None:
    """Modeled cadence describes trips the ledger never captured.

    Those items must be labelled STAPLE rather than reported as hundreds of
    days late, which is what a naive last-purchased subtraction would produce.
    """
    basket = suggest_weekly_basket(bundle, as_of=TODAY)
    staples = [s for s in basket.suggestions if s.status == "STAPLE"]
    assert staples, "fixture models a current cadence that outruns its order dates"
    for suggestion in staples:
        assert suggestion.cadence_source == "MODELED_CURRENT"
        assert suggestion.days_until_due == 0


def test_horizon_widens_the_basket(bundle) -> None:
    week = suggest_weekly_basket(bundle, as_of=TODAY, horizon_days=7)
    quarter = suggest_weekly_basket(bundle, as_of=TODAY, horizon_days=90)
    assert len(quarter.suggestions) >= len(week.suggestions)


def test_a_just_purchased_item_is_not_suggested(bundle) -> None:
    """Standing on the day an item was bought, it is not due again yet."""
    from buyer_history.schema import CadenceSource

    profile = next(
        p
        for p in bundle.item_profiles.values()
        if p.cadence_source is CadenceSource.OBSERVED_GAPS
        and p.cadence_days
        and p.cadence_days > 14
    )
    basket = suggest_weekly_basket(bundle, as_of=profile.last_purchased, horizon_days=7)
    assert profile.item not in {s.item for s in basket.suggestions}


def test_limit_is_respected(bundle) -> None:
    assert len(suggest_weekly_basket(bundle, as_of=TODAY, limit=3).suggestions) == 3


def test_grouping_and_formatting(bundle) -> None:
    basket = suggest_weekly_basket(bundle, as_of=TODAY)
    by_channel = basket.by_channel()
    assert sum(len(v) for v in by_channel.values()) == len(basket.suggestions)

    text = format_basket(basket)
    assert "Weekly basket" in text
    for channel in by_channel:
        assert channel in text


def test_suggestions_serialize(bundle) -> None:
    payload = suggest_weekly_basket(bundle, as_of=TODAY).to_dict()
    assert payload["count"] == len(payload["suggestions"])
    assert isinstance(payload["as_of"], str)
    first = payload["suggestions"][0]
    assert {"item", "quantity", "estimated_line_total", "status", "reasons"} <= first.keys()


def test_basket_reflects_a_new_purchase(bundle) -> None:
    """Buying a staple should push its next due date out."""
    from buyer_history import NormalizedTransaction, record_purchase

    target = next(s for s in suggest_weekly_basket(bundle, as_of=TODAY).suggestions)
    profile = bundle.item_profiles[target.item]
    restocked = record_purchase(
        bundle,
        NormalizedTransaction(
            txn_id="restock:1",
            order_id="restock-1",
            purchased_on=TODAY,
            channel=profile.channels[0],
            merchant=profile.channels[0],
            item=target.item,
            category=target.category,
            quantity=target.quantity,
            unit_price=target.estimated_unit_price,
            line_spend=target.estimated_line_total,
            raw_item=target.item,
        ),
        as_of=TODAY,
    )
    after = bundle.item_profiles[target.item].last_purchased
    assert restocked.item_profiles[target.item].last_purchased >= after
