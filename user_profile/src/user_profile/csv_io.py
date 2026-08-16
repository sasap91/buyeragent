"""CSV loaders for the product catalog and buyer fixtures.

The product columns match the schema the comparison UI parses in
`frontend/src/parseProducts.ts`, so the same CSV feeds both sides:

    id,name,category,brand,price,quality,sustainability

Buyer rows carry the four preference weights plus optional hard filters.
`brand_affinities` is a pipe-separated list of `brand:score` pairs, since CSV has
no native mapping type:

    id,name,price_weight,quality_weight,brand_weight,sustainability_weight,brand_affinities,max_price,min_quality
    maya,Maya,0.55,0.25,0.10,0.10,Generic:0.40|MrCoffee:0.50,150,
"""

from __future__ import annotations

import csv
from pathlib import Path

from user_profile.preferences import User, UserPreferences
from user_profile.product import Product

PRODUCT_COLUMNS = ("id", "name", "category", "brand", "price", "quality", "sustainability")


def _require_columns(reader: csv.DictReader, required: tuple[str, ...], path: Path) -> None:
    missing = [column for column in required if column not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"{path}: missing CSV column(s): {', '.join(missing)}")


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def parse_brand_affinities(raw: str | None) -> dict[str, float]:
    """Parse `Brand:0.9|Other:0.5` into a mapping. Empty input yields {}."""
    if not raw or not raw.strip():
        return {}
    affinities: dict[str, float] = {}
    for pair in raw.split("|"):
        pair = pair.strip()
        if not pair:
            continue
        brand, _, score = pair.partition(":")
        if not _:
            raise ValueError(f"malformed brand affinity {pair!r}; expected 'brand:score'")
        affinities[brand.strip()] = float(score)
    return affinities


def load_products(path: str | Path) -> list[Product]:
    """Read a product catalog CSV."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader, PRODUCT_COLUMNS, path)
        return [
            Product(
                id=row["id"].strip(),
                name=row["name"].strip(),
                category=row["category"].strip(),
                brand=row["brand"].strip(),
                price=float(row["price"]),
                quality=float(row["quality"]),
                sustainability=float(row["sustainability"]),
            )
            for row in reader
            if row.get("id", "").strip()
        ]


def load_users(path: str | Path) -> list[User]:
    """Read a buyer fixture CSV."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader, ("id", "name"), path)
        users: list[User] = []
        for row in reader:
            if not row.get("id", "").strip():
                continue
            users.append(
                User(
                    id=row["id"].strip(),
                    name=row["name"].strip(),
                    preferences=UserPreferences(
                        price_weight=float(row.get("price_weight") or 0.25),
                        quality_weight=float(row.get("quality_weight") or 0.25),
                        brand_weight=float(row.get("brand_weight") or 0.25),
                        sustainability_weight=float(row.get("sustainability_weight") or 0.25),
                        brand_affinities=parse_brand_affinities(row.get("brand_affinities")),
                        max_price=_optional_float(row.get("max_price")),
                        min_quality=_optional_float(row.get("min_quality")),
                    ),
                )
            )
        return users
