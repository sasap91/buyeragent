"""Guards the regression that left `user_profile` unimportable on main.

`__init__.py` re-exports `load_products` / `load_users`, so a missing csv_io or
missing fixture breaks `import user_profile` for every consumer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import user_profile
from user_profile.csv_io import load_products, load_users, parse_brand_affinities

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_package_imports_cleanly() -> None:
    assert user_profile.load_products is load_products
    assert user_profile.load_users is load_users


def test_example_fixtures_exist() -> None:
    assert (EXAMPLES / "products.csv").is_file()
    assert (EXAMPLES / "users.csv").is_file()


def test_products_load_with_valid_ranges() -> None:
    products = load_products(EXAMPLES / "products.csv")
    assert len(products) == 12
    for product in products:
        assert product.price >= 0
        assert 0.0 <= product.quality <= 1.0
        assert 0.0 <= product.sustainability <= 1.0


def test_users_load_with_preferences() -> None:
    users = load_users(EXAMPLES / "users.csv")
    assert {u.id for u in users} == {"maya", "jordan", "riley"}

    maya = next(u for u in users if u.id == "maya")
    assert maya.preferences.price_weight == pytest.approx(0.55)
    assert maya.preferences.max_price == pytest.approx(150.0)
    assert maya.preferences.min_quality is None

    jordan = next(u for u in users if u.id == "jordan")
    assert jordan.preferences.brand_affinities["Sony"] == pytest.approx(0.95)
    assert jordan.preferences.min_quality == pytest.approx(0.70)


def test_brand_affinity_parsing() -> None:
    assert parse_brand_affinities("Sony:0.95|Nike:0.9") == {"Sony": 0.95, "Nike": 0.9}
    assert parse_brand_affinities("") == {}
    assert parse_brand_affinities(None) == {}
    with pytest.raises(ValueError):
        parse_brand_affinities("SonyNoScore")


def test_missing_column_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("id,name\nx,Thing\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing CSV column"):
        load_products(bad)


def test_catalog_feeds_the_ranking_pipeline() -> None:
    products = load_products(EXAMPLES / "products.csv")
    users = load_users(EXAMPLES / "users.csv")
    feed = user_profile.filter_feed(users[0], products)
    assert feed and all(p in products for p in feed)
