"""Generate the synthetic household workbook used by the demo and tests.

The real workbook holds one household's actual purchase history and is
gitignored. This fixture stands in for it: same schema, same structural
properties, entirely invented buyer, orders and dates.

It is built to exercise every branch the module cares about:
  * two channels with different column layouts (seller vs unit price)
  * recurring items with a measurable cadence, and one-off items
  * one category where the buyer absorbs a price rise      -> LOW sensitivity
  * one category where the buyer steps back down from a spike -> HIGH sensitivity
  * branded goods and unbranded commodity produce
  * premium attributes (organic, grass-fed, cage-free, wild-caught)
  * a modeled current cadence that outruns the recorded order dates
  * noise rows covering every exclusion rule

Product brands are real consumer brands so the brand lexicon is exercised; the
buyer, orders, dates and prices are not.

    python3 buyer_history/fixtures/make_synthetic_workbook.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xlsx_writer import write_workbook  # noqa: E402

OUT = Path(__file__).resolve().parent / "synthetic_household.xlsx"

EXCEL_EPOCH = date(1899, 12, 30)

CHANNEL_A = "Evermart"  # marketplace: shelf-stable, bulk, supplements
CHANNEL_B = "FreshCart"  # grocery: produce, seafood, meat


def serial(value: str) -> int:
    return (date.fromisoformat(value) - EXCEL_EPOCH).days


# (date, order, item, category, qty, line spend, seller, raw item, weight)
CHANNEL_A_ROWS: tuple[tuple, ...] = (
    ("2026-01-05", "EM-1001", "Rolled Oats", "Groceries > Grains & Seeds", 1, 12.99,
     "Anthony's Goods", "Anthony's Organic Rolled Oats, 3 lb, Non GMO, Gluten Free", 1),
    ("2026-01-05", "EM-1001", "Toilet Paper", "Household > Paper", 1, 27.99,
     "Evermart Retail", "Soft & Strong 2-Ply Toilet Paper, 30 Ultra Rolls", 1),
    ("2026-01-12", "EM-1002", "Whole Bean Coffee", "Groceries > Coffee", 1, 15.99,
     "Evermart Retail", "Lavazza Espresso Whole Bean Coffee, Medium Roast, 2.2 lb Bag", 1),
    ("2026-01-12", "EM-1002", "Honey", "Groceries > Pantry", 1, 11.49,
     "Northgate Foods", "Raw Wildflower Honey, Unfiltered, 24 oz", 0.65),
    ("2026-02-16", "EM-1003", "Whey Protein", "Groceries > Protein", 1, 84.99,
     "Anthony's Goods", "Anthony's Grass Fed Whey Protein Powder, Unflavored, No Additives", 1),
    ("2026-02-16", "EM-1003", "Daily Multivitamin", "Health > Supplements", 1, 24.99,
     "Evermart Retail", "Nature Made Daily Multivitamin, 120 Count", 1),
    ("2026-03-09", "EM-1004", "Whole Bean Coffee", "Groceries > Coffee", 1, 64.99,
     "Northgate Foods", "Subtle Earth Organic Coffee, Medium Dark Roast, Whole Bean, 5 lb Bulk", 1),
    ("2026-03-09", "EM-1004", "Dishwasher Detergent", "Household > Cleaning", 1, 8.29,
     "Evermart Retail", "Cascade Complete Gel Dishwasher Detergent, 75 oz", 0.65),
    ("2026-04-06", "EM-1005", "Rolled Oats", "Groceries > Grains & Seeds", 1, 13.49,
     "Anthony's Goods", "Anthony's Organic Rolled Oats, 3 lb, Non GMO, Gluten Free", 1),
    ("2026-04-20", "EM-1006", "Whey Protein", "Groceries > Protein", 1, 94.99,
     "Anthony's Goods", "Anthony's Grass Fed Whey Protein Powder, Unflavored, No Additives", 1),
    ("2026-05-11", "EM-1007", "Whole Bean Coffee", "Groceries > Coffee", 1, 16.49,
     "Evermart Retail", "Lavazza Espresso Whole Bean Coffee, Medium Roast, 2.2 lb Bag", 1),
    ("2026-05-11", "EM-1007", "Razor Blades", "Personal Care > Grooming", 1, 31.99,
     "Evermart Retail", "Gillette Mach3 Razor Blades, 3-Blade Refills, 15 Count", 0.65),
    ("2026-06-01", "EM-1008", "Toilet Paper", "Household > Paper", 1, 7.49,
     "Evermart Retail", "Soft & Strong 2-Ply Toilet Paper, 6 Ultra Rolls", 1),
    ("2026-06-15", "EM-1009", "Daily Multivitamin", "Health > Supplements", 1, 26.49,
     "Evermart Retail", "Nature Made Daily Multivitamin, 120 Count", 1),
    ("2026-06-15", "EM-1009", "Vitamin D3 Supplement", "Health > Supplements", 1, 14.99,
     "Evermart Retail", "Solgar Vitamin D3 2000 IU, 100 Softgels", 0.65),
    ("2026-07-27", "EM-1010", "Whole Bean Coffee", "Groceries > Coffee", 1, 14.99,
     "Evermart Retail", "Lavazza Espresso Whole Bean Coffee, Medium Roast, 2.2 lb Bag", 1),
    ("2026-07-27", "EM-1010", "Whey Protein", "Groceries > Protein", 1, 94.99,
     "Anthony's Goods", "Anthony's Grass Fed Whey Protein Powder, Unflavored, No Additives", 1),
)

# (date, order, item, category, qty, unit price, raw item, weight)
CHANNEL_B_ROWS: tuple[tuple, ...] = (
    ("2025-09-14", "FC-7001", "Kale", "Produce > Greens & Herbs", 1, 3.19, "Green Curly Kale, 1 bunch", 1),
    ("2025-09-14", "FC-7001", "Green Onion", "Produce > Greens & Herbs", 2, 0.69, "Green Onion, 1 bunch", 1),
    ("2025-09-14", "FC-7001", "Broccoli", "Produce > Vegetables", 1, 3.99, "Broccoli Crowns, 2 lb", 1),
    ("2025-09-14", "FC-7001", "Carrots", "Produce > Vegetables", 1, 1.29, "Carrots, 1 lb", 1),
    ("2025-09-14", "FC-7001", "Cilantro", "Produce > Greens & Herbs", 2, 0.89, "Cilantro, 1 bunch", 1),
    ("2025-09-14", "FC-7001", "Tomatoes", "Produce > Vegetables", 1, 3.29, "Cluster Tomatoes, 2 lb", 0.65),

    ("2025-10-05", "FC-7002", "Kale", "Produce > Greens & Herbs", 1, 3.29, "Green Curly Kale, 1 bunch", 1),
    ("2025-10-05", "FC-7002", "Green Onion", "Produce > Greens & Herbs", 2, 0.59, "Green Onion, 1 bunch", 1),
    ("2025-10-05", "FC-7002", "Cilantro", "Produce > Greens & Herbs", 1, 0.99, "Cilantro, 1 bunch", 1),
    ("2025-10-05", "FC-7002", "Whole Chicken", "Meat & Poultry", 1, 14.99,
     "Free Range Whole Chicken, Cut Up, 3-3.5 lb", 1),
    ("2025-10-05", "FC-7002", "Tilapia", "Seafood", 1, 6.79, "Whole Tilapia, Gutted and Scaled, Frozen, 2 lb", 1),
    ("2025-10-05", "FC-7002", "Broccoli", "Produce > Vegetables", 1, 4.29, "Broccoli Crowns, 2 lb", 1),

    ("2025-11-02", "FC-7003", "Kale", "Produce > Greens & Herbs", 1, 2.99, "Green Curly Kale, 1 bunch", 1),
    ("2025-11-02", "FC-7003", "Green Onion", "Produce > Greens & Herbs", 1, 0.69, "Green Onion, 1 bunch", 1),
    ("2025-11-02", "FC-7003", "Carrots", "Produce > Vegetables", 1, 1.19, "Carrots, 1 lb", 1),
    ("2025-11-02", "FC-7003", "Napa Cabbage", "Produce > Vegetables", 1, 2.89, "Napa Cabbage, 1 count", 0.65),
    ("2025-11-02", "FC-7003", "Soy Sauce", "Pantry > Sauces & Condiments", 1, 5.49,
     "Lee Kum Kee Premium Soy Sauce, Sodium Reduced, 500 ml", 1),
    ("2025-11-02", "FC-7003", "Jasmine Rice", "Pantry > Staples", 1, 16.99,
     "Elephant Brand Thai Jasmine Rice, 10 lb", 1),

    ("2025-12-07", "FC-7004", "Kale", "Produce > Greens & Herbs", 1, 3.29, "Green Curly Kale, 1 bunch", 1),
    ("2025-12-07", "FC-7004", "Cilantro", "Produce > Greens & Herbs", 2, 0.89, "Cilantro, 1 bunch", 1),
    ("2025-12-07", "FC-7004", "Broccoli", "Produce > Vegetables", 1, 3.79, "Broccoli Crowns, 2 lb", 1),
    ("2025-12-07", "FC-7004", "Golden Pompano", "Seafood", 2, 5.29,
     "Oceankist Golden Pompano, Wild Caught, Gutted, 350-450 g", 1),
    ("2025-12-07", "FC-7004", "Whole Chicken", "Meat & Poultry", 1, 15.29,
     "Free Range Whole Chicken, Cut Up, 3-3.5 lb", 1),

    ("2026-01-11", "FC-7005", "Green Onion", "Produce > Greens & Herbs", 2, 0.79, "Green Onion, 1 bunch", 1),
    ("2026-01-11", "FC-7005", "Carrots", "Produce > Vegetables", 1, 1.39, "Carrots, 1 lb", 1),
    ("2026-01-11", "FC-7005", "Tilapia", "Seafood", 1, 6.99, "Whole Tilapia, Gutted and Scaled, Frozen, 2 lb", 1),
    ("2026-01-11", "FC-7005", "Kale", "Produce > Greens & Herbs", 1, 3.09, "Green Curly Kale, 1 bunch", 1),
    ("2026-01-11", "FC-7005", "Bok Choy", "Produce > Vegetables", 1, 2.79, "Baby Bok Choy, 1 lb", 0.65),

    ("2026-02-08", "FC-7006", "Kale", "Produce > Greens & Herbs", 1, 3.19, "Green Curly Kale, 1 bunch", 1),
    ("2026-02-08", "FC-7006", "Green Onion", "Produce > Greens & Herbs", 2, 0.69, "Green Onion, 1 bunch", 1),
    ("2026-02-08", "FC-7006", "Cilantro", "Produce > Greens & Herbs", 1, 0.99, "Cilantro, 1 bunch", 1),
    ("2026-02-08", "FC-7006", "Golden Pompano", "Seafood", 3, 5.49,
     "Oceankist Golden Pompano, Wild Caught, Gutted, 350-450 g", 1),
    ("2026-02-08", "FC-7006", "Broccoli", "Produce > Vegetables", 1, 4.09, "Broccoli Crowns, 2 lb", 1),
    ("2026-02-08", "FC-7006", "Apples", "Produce > Fruit", 1, 8.99, "Honeycrisp Apples, 3 lb", 1),

    ("2026-03-15", "FC-7007", "Carrots", "Produce > Vegetables", 1, 1.29, "Carrots, 1 lb", 1),
    ("2026-03-15", "FC-7007", "Whole Chicken", "Meat & Poultry", 1, 15.49,
     "Free Range Whole Chicken, Cut Up, 3-3.5 lb", 1),
    ("2026-03-15", "FC-7007", "Kale", "Produce > Greens & Herbs", 1, 3.29, "Green Curly Kale, 1 bunch", 1),
    ("2026-03-15", "FC-7007", "Green Onion", "Produce > Greens & Herbs", 1, 0.59, "Green Onion, 1 bunch", 1),
    ("2026-03-15", "FC-7007", "Ginger", "Produce > Vegetables", 1, 1.79, "Ginger Root, 1 lb", 1),
    ("2026-03-15", "FC-7007", "Garlic", "Produce > Vegetables", 2, 2.29, "Sleeved Garlic, 5 count", 1),

    ("2026-04-12", "FC-7008", "Kale", "Produce > Greens & Herbs", 1, 2.99, "Green Curly Kale, 1 bunch", 1),
    ("2026-04-12", "FC-7008", "Cilantro", "Produce > Greens & Herbs", 2, 0.89, "Cilantro, 1 bunch", 1),
    ("2026-04-12", "FC-7008", "Broccoli", "Produce > Vegetables", 1, 3.89, "Broccoli Crowns, 2 lb", 1),
    ("2026-04-12", "FC-7008", "Golden Pompano", "Seafood", 2, 5.29,
     "Oceankist Golden Pompano, Wild Caught, Gutted, 350-450 g", 1),
    ("2026-04-12", "FC-7008", "Jasmine Rice", "Pantry > Staples", 1, 17.49,
     "Elephant Brand Thai Jasmine Rice, 10 lb", 1),
    ("2026-04-12", "FC-7008", "Green Onion", "Produce > Greens & Herbs", 1, 0.69, "Green Onion, 1 bunch", 1),
)

# The grocery channel understates current cadence: this household now shops a
# store whose receipts are not captured, so a rescaled figure is supplied.
MODELED_ITEM_OCCASIONS: tuple[tuple[str, float], ...] = (
    ("Kale", 5.2),
    ("Green Onion", 5.2),
    ("Broccoli", 3.5),
    ("Cilantro", 3.5),
    ("Carrots", 2.6),
    ("Golden Pompano", 2.6),
)

MODELED_CATEGORY_TRIPS: tuple[tuple[str, float], ...] = (
    ("Produce > Greens & Herbs", 6.9),
    ("Produce > Vegetables", 6.9),
    ("Seafood", 3.5),
    ("Meat & Poultry", 2.6),
)

EXCLUDED_ROWS: tuple[tuple, ...] = (
    (CHANNEL_A, "2026-01-20", "EM-9001", "Streamly Plus - monthly subscription",
     "Digital Subscription",
     "Exclude: Digital Subscription is not useful for household purchase-preference training"),
    (CHANNEL_A, "2026-02-03", "EM-9002", "Countertop Blender Pro, 900W, 6-Speed", "Kitchen",
     "Exclude: one-off durable purchase; high risk of adding noise to recurring household model"),
    (CHANNEL_A, "2026-03-22", "EM-9003", "The Long Afternoon - paperback", "Books & Media",
     "Exclude: Books & Media is not useful for household purchase-preference training"),
    (CHANNEL_A, "2026-04-18", "EM-9004", "Wide Ruled Legal Pads, 12 Pack", "Office & Stationery",
     "Exclude: Office & Stationery is not useful for household purchase-preference training"),
    (CHANNEL_A, "2026-05-30", "EM-9005", "Cold & Flu Relief Tablets, 24 ct",
     "Health & Personal Care",
     "Exclude: episodic/medical purchase; not a stable household preference signal"),
    (CHANNEL_B, "2026-02-08", "FC-7006", "Anniversary tote bag, 1 each (FREE gift)", "Non-food",
     "Exclude: free promotional item; not a purchase-preference signal"),
)


def build_sheets() -> dict[str, list[list[object]]]:
    channel_a = [[
        "Date", "Channel", "Order ID", "Item (Normalized)", "Category",
        "Qty", "Line Spend USD", "Seller", "Raw Item", "Model Weight",
    ]]
    for day, order, item, category, qty, spend, seller, raw, weight in CHANNEL_A_ROWS:
        channel_a.append(
            [serial(day), CHANNEL_A, order, item, category, qty, spend, seller, raw, weight]
        )

    channel_b = [[
        "Date", "Channel", "Order ID", "Item (Normalized)", "Category",
        "Qty", "Unit Price USD", "Line Spend USD", "Raw Item", "Model Weight",
    ]]
    for day, order, item, category, qty, unit, raw, weight in CHANNEL_B_ROWS:
        channel_b.append(
            [serial(day), CHANNEL_B, order, item, category, qty, unit,
             round(unit * qty, 2), raw, weight]
        )

    item_profile = [["Channel", "Item", "Modeled Current Monthly Occasions"]]
    for item, occasions in MODELED_ITEM_OCCASIONS:
        item_profile.append([CHANNEL_B, item, occasions])

    category_profile = [["Channel", "Category", "Modeled Current Monthly Trip Occurrences"]]
    for category, trips in MODELED_CATEGORY_TRIPS:
        category_profile.append([CHANNEL_B, category, trips])

    excluded = [["Channel", "Date", "Order ID", "Raw Item", "Source Category", "Reason"]]
    for channel, day, order, raw, category, reason in EXCLUDED_ROWS:
        excluded.append([channel, serial(day), order, raw, category, reason])

    readme = [
        ["MandateLab - SYNTHETIC household fixture"],
        [],
        ["Field", "Value"],
        ["Purpose", "Stands in for the real household workbook, which is gitignored."],
        ["Buyer", "Invented. No real person, order, date or price appears here."],
        ["Channels", f"{CHANNEL_A} (shelf-stable, bulk, supplements); "
                     f"{CHANNEL_B} (produce, seafood, meat)"],
        ["Cadence note", f"{CHANNEL_B} order dates understate current shopping frequency; "
                         "use the modeled monthly figures as the cadence prior."],
        ["Regenerate", "python3 buyer_history/fixtures/make_synthetic_workbook.py"],
    ]

    return {
        "README": readme,
        f"{CHANNEL_A}_Clean": channel_a,
        f"{CHANNEL_B}_Clean": channel_b,
        "Item_Profile": item_profile,
        "Category_Profile": category_profile,
        "Excluded_Items": excluded,
    }


def main() -> None:
    path = write_workbook(OUT, build_sheets())
    print(f"wrote {path}")
    print(f"  {len(CHANNEL_A_ROWS)} {CHANNEL_A} lines, {len(CHANNEL_B_ROWS)} {CHANNEL_B} lines, "
          f"{len(EXCLUDED_ROWS)} excluded")


if __name__ == "__main__":
    main()
