"""Noise removal.

The source workbook already ships an `Excluded_Items` sheet with a stated
taxonomy. These rules encode that same taxonomy so the filter can be re-applied
to *new* transactions during continuous learning, not just to the fixture.

The goal is a stable household-preference signal, so we drop lines that are
real purchases but poor evidence of what the household repeatedly wants:
subscriptions, media, stationery, episodic medical items, one-off durables and
free promotional items.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from buyer_history.schema import ExcludedTransaction, NormalizedTransaction

DURABLE_RULE = "ONE_OFF_DURABLE"


@dataclass(frozen=True)
class NoiseRule:
    code: str
    reason: str
    category_tokens: tuple[str, ...] = ()
    item_pattern: str | None = None

    def matches(self, raw_item: str, category: str) -> bool:
        category_l = category.lower()
        if any(token in category_l for token in self.category_tokens):
            return True
        if self.item_pattern and re.search(self.item_pattern, raw_item, re.IGNORECASE):
            return True
        return False


# Ordered: the first matching rule wins, so the specific ones come first.
RULES: tuple[NoiseRule, ...] = (
    NoiseRule(
        code="DIGITAL_SUBSCRIPTION",
        reason="Digital subscription is not useful for household purchase-preference training",
        category_tokens=("digital subscription",),
        item_pattern=r"\b(subscription|membership|prime student|prime video|kindle unlimited)\b",
    ),
    NoiseRule(
        code="BOOKS_MEDIA",
        reason="Books & media is not useful for household purchase-preference training",
        category_tokens=("books & media", "books and media"),
        item_pattern=r"\b(kindle ebook|e-?book|paperback|hardcover|tvod)\b",
    ),
    NoiseRule(
        code="OFFICE_STATIONERY",
        reason="Office & stationery is not useful for household purchase-preference training",
        category_tokens=("office & stationery", "office and stationery"),
    ),
    NoiseRule(
        code="EPISODIC_MEDICAL",
        reason="Episodic or medical purchase; not a stable household preference signal",
        category_tokens=("health & personal care", "health and personal care", "otc medicine"),
    ),
    NoiseRule(
        code="PROMOTIONAL_ITEM",
        reason="Free promotional item; not a purchase-preference signal",
        category_tokens=("non-food",),
        item_pattern=r"\bfree gift\b|\(free\b",
    ),
    NoiseRule(
        code=DURABLE_RULE,
        reason="One-off durable purchase; high risk of adding noise to a recurring household model",
        category_tokens=("kitchen", "electronics & tech", "home & bath", "home and bath"),
        item_pattern=r"\bprotection plan\b",
    ),
)


class NoiseFilter:
    """Applies the exclusion taxonomy to normalized transactions.

    `exclude_durables` exists because the household model treats durables as
    noise, but a MandateLab mission for a durable (headphones, say) needs that
    history retained. Callers building a durable-category profile turn it off.
    """

    def __init__(self, exclude_durables: bool = True) -> None:
        self.exclude_durables = exclude_durables

    @property
    def rules(self) -> tuple[NoiseRule, ...]:
        if self.exclude_durables:
            return RULES
        return tuple(rule for rule in RULES if rule.code != DURABLE_RULE)

    def classify(self, raw_item: str, category: str) -> NoiseRule | None:
        for rule in self.rules:
            if rule.matches(raw_item, category):
                return rule
        return None

    def split(
        self,
        transactions: Iterable[NormalizedTransaction],
    ) -> tuple[list[NormalizedTransaction], list[ExcludedTransaction]]:
        kept: list[NormalizedTransaction] = []
        dropped: list[ExcludedTransaction] = []
        for txn in transactions:
            rule = self.classify(txn.raw_item or txn.item, txn.category)
            if rule is None:
                kept.append(txn)
                continue
            dropped.append(
                ExcludedTransaction(
                    raw_item=txn.raw_item or txn.item,
                    category=txn.category,
                    channel=txn.channel,
                    reason=rule.reason,
                    rule=rule.code,
                    order_id=txn.order_id,
                    purchased_on=txn.purchased_on,
                )
            )
        return kept, dropped


# Maps the workbook's own exclusion wording onto our rule codes, so exclusions
# the source made and exclusions we make are reported under one taxonomy.
_REASON_HINTS: tuple[tuple[str, str], ...] = (
    ("digital subscription", "DIGITAL_SUBSCRIPTION"),
    ("books & media", "BOOKS_MEDIA"),
    ("office & stationery", "OFFICE_STATIONERY"),
    ("episodic", "EPISODIC_MEDICAL"),
    ("medical", "EPISODIC_MEDICAL"),
    ("promotional", "PROMOTIONAL_ITEM"),
    ("free gift", "PROMOTIONAL_ITEM"),
    ("one-off durable", DURABLE_RULE),
)


def excluded_from_sheet(records: Sequence[dict[str, str]]) -> list[ExcludedTransaction]:
    """Carry the workbook's own Excluded_Items rows through for auditability."""
    from buyer_history.xlsx import excel_serial_to_date

    rows: list[ExcludedTransaction] = []
    for record in records:
        reason = record.get("Reason", "")
        lowered = reason.lower()
        code = next(
            (code for hint, code in _REASON_HINTS if hint in lowered),
            "WORKBOOK_EXCLUSION",
        )
        rows.append(
            ExcludedTransaction(
                raw_item=record.get("Raw Item", ""),
                category=record.get("Source Category", ""),
                channel=record.get("Channel", ""),
                reason=reason,
                rule=code,
                order_id=record.get("Order ID", ""),
                purchased_on=excel_serial_to_date(record.get("Date")),
            )
        )
    return rows
