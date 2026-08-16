"""Normalize Amazon and Weee! rows into one common transaction schema.

Amazon and Weee! ship different columns (Amazon has a Seller and no unit price;
Weee! has a unit price and no seller), so this module reconciles them into
`NormalizedTransaction` while preserving channel, category and the per-row
`Model Weight` the workbook uses to mark signal reliability.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from buyer_history.noise import NoiseFilter, excluded_from_sheet
from buyer_history.schema import Condition, ExcludedTransaction, NormalizedTransaction
from buyer_history.xlsx import excel_serial_to_date, read_workbook, sheet_records, to_float

# Brands that appear in the raw item strings. Matched as whole phrases, longest
# first, so "Amazon Basics" wins over a bare "Amazon".
BRAND_NAMES: tuple[str, ...] = (
    "Amazon Basics",
    "Amazon Grocery",
    "Amazon Fresh",
    "Earthbound Farm",
    "Organic Valley",
    "Premium Selection",
    "Elephant Brand",
    "Lee Kum Kee",
    "Subtle Earth",
    "Nature Made",
    "Spicy World",
    "NATURELO",
    "Pompeian",
    "Oceankist",
    "Mitlitsky",
    "Greenfit",
    "Sunmerry",
    "Lavazza",
    "Gillette",
    "Fischer's",
    "Anthony's",
    "Cascade",
    "Vadilal",
    "Talassa",
    "Safoco",
    "Solgar",
    "Kewpie",
    "Aroy-D",
    "Laxmi",
    "Shan",
    "Aara",
    "MDH",
    "TSF",
    "House",
)

_BRAND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE))
    for name in sorted(BRAND_NAMES, key=len, reverse=True)
)

# Sellers that are the brand themselves, used only when the raw item names none.
SELLER_AS_BRAND: frozenset[str] = frozenset(
    {
        "Raw Organic Whey",
        "NATURELO",
        "Truevantage Nutrition",
        "Bayland Health",
        "Amazon Grocery",
    }
)

# Sellers that are marketplace storefronts rather than product brands.
GENERIC_SELLERS: frozenset[str] = frozenset(
    {"Amazon.com", "PriorityShopping", "SimplyBeautiful", "OA Foods", "Anthony's Goods"}
)

ATTRIBUTE_PATTERNS: dict[str, re.Pattern[str]] = {
    "organic": re.compile(r"\borganic\b", re.IGNORECASE),
    "grass_fed": re.compile(r"\bgrass[- ]fed\b", re.IGNORECASE),
    "cage_free": re.compile(r"\bcage[- ]free\b", re.IGNORECASE),
    "free_range": re.compile(r"\bfree[- ]range\b", re.IGNORECASE),
    "wild_caught": re.compile(r"\bwild[- ]caught\b", re.IGNORECASE),
    "non_gmo": re.compile(r"\bnon[- ]?gmo\b", re.IGNORECASE),
    "gluten_free": re.compile(r"\bgluten[- ]free\b", re.IGNORECASE),
    "usda_certified": re.compile(r"\busda\b", re.IGNORECASE),
    "no_additives": re.compile(r"\bno additives\b", re.IGNORECASE),
    "halal": re.compile(r"\bhalal\b", re.IGNORECASE),
    "premium": re.compile(r"\bpremium\b", re.IGNORECASE),
    "arabica": re.compile(r"\barabica\b", re.IGNORECASE),
    "reduced_sodium": re.compile(r"\b(sodium reduced|reduced sodium)\b", re.IGNORECASE),
    "frozen": re.compile(r"\bfrozen\b", re.IGNORECASE),
    "bulk": re.compile(r"\bbulk\b", re.IGNORECASE),
    "unflavored": re.compile(r"\bunflavored\b", re.IGNORECASE),
}

# Attributes that indicate paying up for quality rather than just a form factor.
PREMIUM_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "organic",
        "grass_fed",
        "cage_free",
        "free_range",
        "wild_caught",
        "non_gmo",
        "usda_certified",
        "no_additives",
        "halal",
        "premium",
        "arabica",
    }
)

# (sheet name, fallback channel) pairs for the source workbook layout.
DEFAULT_TRANSACTION_SHEETS: tuple[tuple[str, str], ...] = (
    ("Amazon_Clean", "Amazon"),
    ("Weee_Clean", "Weee!"),
)

_REFURB_RE = re.compile(r"\b(refurbished|renewed|reconditioned)\b", re.IGNORECASE)
_USED_RE = re.compile(r"\b(used|pre-?owned|open box)\b", re.IGNORECASE)
_NEW_RE = re.compile(r"\bbrand new\b", re.IGNORECASE)


def extract_brand(raw_item: str, seller: str | None = None) -> str | None:
    """Brand from the item text, falling back to the seller when it is a brand.

    Returns None for unbranded commodity goods (loose produce, bulk staples).
    That absence is itself a signal: brand cannot drive a decision where the
    buyer has never bought a branded version.
    """
    for name, pattern in _BRAND_PATTERNS:
        if pattern.search(raw_item):
            return name
    if seller and seller in SELLER_AS_BRAND:
        return seller
    return None


def extract_attributes(raw_item: str) -> list[str]:
    return sorted(tag for tag, pattern in ATTRIBUTE_PATTERNS.items() if pattern.search(raw_item))


def detect_condition(raw_item: str) -> Condition:
    """Condition is rarely stated in grocery data; UNKNOWN is the honest default."""
    if _REFURB_RE.search(raw_item):
        return Condition.REFURBISHED
    if _USED_RE.search(raw_item):
        return Condition.USED
    if _NEW_RE.search(raw_item):
        return Condition.NEW
    return Condition.UNKNOWN


def discover_transaction_sheets(
    workbook: dict[str, list[list[str]]],
) -> tuple[tuple[str, str], ...]:
    """Find the transaction sheets in a workbook by the `<Channel>_Clean` convention.

    Lets the real workbook (Amazon_Clean, Weee_Clean) and the synthetic fixture
    (Evermart_Clean, FreshCart_Clean) load through the same call with no
    configuration. Falls back to the known layout when nothing matches.
    """
    found = tuple(
        (name, name[: -len("_Clean")])
        for name in workbook
        if name.endswith("_Clean") and len(name) > len("_Clean")
    )
    return found or DEFAULT_TRANSACTION_SHEETS


@dataclass
class LoadedHistory:
    """Everything pulled out of the source workbook."""

    transactions: list[NormalizedTransaction] = field(default_factory=list)
    excluded: list[ExcludedTransaction] = field(default_factory=list)
    # (channel, item) -> modeled current monthly purchase occasions.
    modeled_monthly_occasions: dict[tuple[str, str], float] = field(default_factory=dict)
    # channel -> modeled current monthly trips containing a category.
    modeled_category_occasions: dict[tuple[str, str], float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _row_to_transaction(
    record: dict[str, str],
    index: int,
    sheet: str,
    default_channel: str,
) -> NormalizedTransaction | None:
    purchased_on = excel_serial_to_date(record.get("Date"))
    item = record.get("Item (Normalized)", "").strip()
    if purchased_on is None or not item:
        return None

    channel = record.get("Channel", "").strip() or default_channel
    order_id = record.get("Order ID", "").strip()
    quantity = to_float(record.get("Qty"), 1.0) or 1.0
    line_spend = to_float(record.get("Line Spend USD"))
    unit_price = to_float(record.get("Unit Price USD"))
    if unit_price <= 0:
        unit_price = line_spend / quantity if quantity else line_spend

    seller = record.get("Seller", "").strip() or None
    raw_item = record.get("Raw Item", "").strip()
    merchant = seller if seller else channel

    return NormalizedTransaction(
        txn_id=f"{channel}:{order_id}:{index}",
        order_id=order_id,
        purchased_on=purchased_on,
        channel=channel,
        merchant=merchant,
        item=item,
        category=record.get("Category", "").strip(),
        quantity=quantity,
        unit_price=round(unit_price, 4),
        line_spend=round(line_spend, 2),
        raw_item=raw_item,
        brand=extract_brand(raw_item, None if seller in GENERIC_SELLERS else seller),
        attributes=extract_attributes(raw_item),
        condition=detect_condition(raw_item),
        model_weight=to_float(record.get("Model Weight"), 1.0) or 1.0,
        source_sheet=sheet,
    )


def load_workbook_history(
    path: str | Path,
    noise_filter: NoiseFilter | None = None,
    transaction_sheets: Sequence[tuple[str, str]] | None = None,
) -> LoadedHistory:
    """Read a MandateLab workbook into normalized, noise-filtered transactions.

    `transaction_sheets` is a sequence of (sheet name, fallback channel) pairs.
    The sheet name is a structural slot, not a retailer: the synthetic fixture
    uses its own sheet names and channels while implementing the same schema.
    """
    noise_filter = noise_filter or NoiseFilter()
    workbook = read_workbook(path)
    history = LoadedHistory()

    transaction_sheets = transaction_sheets or discover_transaction_sheets(workbook)
    raw: list[NormalizedTransaction] = []
    for sheet, default_channel in transaction_sheets:
        if sheet not in workbook:
            history.notes.append(f"sheet {sheet} not present in workbook")
            continue
        for index, record in enumerate(sheet_records(workbook[sheet])):
            txn = _row_to_transaction(record, index, sheet, default_channel)
            if txn is not None:
                raw.append(txn)

    kept, dropped = noise_filter.split(raw)
    history.transactions = sorted(kept, key=lambda t: (t.purchased_on, t.order_id, t.item))
    history.excluded = dropped

    # The workbook lists its own exclusions on a separate sheet; keep them so the
    # full audit trail survives, but do not double count anything we re-derived.
    if "Excluded_Items" in workbook:
        history.excluded.extend(excluded_from_sheet(sheet_records(workbook["Excluded_Items"])))

    # The README is explicit that sparse Weee! order dates understate the current
    # grocery cadence (the household now shops H Mart ~2x/week), and supplies a
    # rescaled figure. Carry it through so cadence uses it instead of raw gaps.
    if "Item_Profile" in workbook:
        for record in sheet_records(workbook["Item_Profile"]):
            modeled = to_float(record.get("Modeled Current Monthly Occasions"))
            if modeled > 0:
                key = (record.get("Channel", "").strip(), record.get("Item", "").strip())
                history.modeled_monthly_occasions[key] = modeled

    if "Category_Profile" in workbook:
        for record in sheet_records(workbook["Category_Profile"]):
            modeled = to_float(record.get("Modeled Current Monthly Trip Occurrences"))
            if modeled > 0:
                key = (record.get("Channel", "").strip(), record.get("Category", "").strip())
                history.modeled_category_occasions[key] = modeled

    return history
