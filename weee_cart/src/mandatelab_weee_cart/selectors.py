"""Weee! page selectors, isolated so calibration is a one-file edit.

These are best-effort guesses written without access to the live DOM. When a run
reports NOT_FOUND or AMBIGUOUS, fix the entry here rather than touching the
executor: nothing else in this package knows what the page looks like.

To calibrate, open Weee!, search for an item, and inspect the result tile:
  * SEARCH_URL      — the search results URL pattern
  * PRODUCT_TILE    — one result card
  * TILE_TITLE      — the product name inside a card
  * TILE_PRICE      — the displayed price inside a card
  * ADD_TO_CART     — the add button inside a card
  * CART_COUNT      — the header badge showing cart item count
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEARCH_URL = "https://www.sayweee.com/en/search?keyword={query}"
CART_URL = "https://www.sayweee.com/en/cart"


@dataclass(frozen=True)
class Selectors:
    """CSS selectors, each with fallbacks tried in order."""

    product_tile: tuple[str, ...] = (
        "a[href*='/product/']",
        "[data-testid='product-card']",
        "[class*='product-card']",
    )
    tile_title: tuple[str, ...] = (
        "[data-testid='product-title']",
        "[class*='product-title']",
        "[class*='ProductTitle']",
        "h3",
    )
    tile_price: tuple[str, ...] = (
        "[data-testid='product-price']",
        "[class*='product-price']",
        "[class*='Price']",
    )
    # Calibrated against the live site. Weee!'s tile carries a mini add-to-cart
    # control whose plus button is the real target.
    #
    # Do NOT reintroduce a loose `button[aria-label*='Add' i]` fallback: the same
    # tile has an "Add to favorites" button, and that selector matches it first.
    add_to_cart: tuple[str, ...] = (
        "[data-testid='btn-atc-plus']",
        "button[aria-label='Increase quantity by one']",
        "[data-testid='add-to-cart']",
        "button[class*='add-cart']",
    )
    cart_count: tuple[str, ...] = (
        "[data-testid='cart-count']",
        "[class*='cart-count']",
        "[class*='CartCount']",
    )
    login_marker: tuple[str, ...] = (
        "a[href*='/login']",
        "[class*='login']",
    )
    extra: dict[str, tuple[str, ...]] = field(default_factory=dict)


DEFAULT = Selectors()
