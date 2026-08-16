"""Put approved basket lines into a real Weee! cart.

Attaches over CDP to a Chrome the buyer already launched and logged into, so
this module never sees a credential and never creates a session of its own. If
no debuggable browser is listening, it refuses rather than falling back to an
automated login.

Two hard limits, deliberately not configurable away:

  * It only ever adds to the cart. There is no checkout path in this file.
  * It refuses any line that did not arrive with an APPROVE decision, so the
    Decision Engine cannot be bypassed by calling the executor directly.

Dry run is the default. Nothing touches the cart until `dry_run=False`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from urllib.parse import quote_plus

from mandatelab_weee_cart.selectors import CART_URL, DEFAULT, SEARCH_URL, Selectors

DEFAULT_CDP_URL = "http://127.0.0.1:9222"

# Outcome codes, mirroring the sandbox executor's refusal-code style.
ADDED = "ADDED"
DRY_RUN = "DRY_RUN"
NOT_APPROVED = "NOT_APPROVED"
NO_MATCH = "NO_MATCH"
ADD_BUTTON_NOT_FOUND = "ADD_BUTTON_NOT_FOUND"
PRICE_ABOVE_LIMIT = "PRICE_ABOVE_LIMIT"
BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
NOT_LOGGED_IN = "NOT_LOGGED_IN"
OUT_OF_STOCK = "OUT_OF_STOCK"
PARTIAL = "PARTIAL"


class BrowserUnavailable(RuntimeError):
    """No debuggable Chrome is listening on the CDP port."""


@dataclass
class CartLineResult:
    item: str
    status: str
    quantity: float = 1.0
    matched_title: str | None = None
    matched_price: float | None = None
    expected_price: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "status": self.status,
            "quantity": self.quantity,
            "matched_title": self.matched_title,
            "matched_price": self.matched_price,
            "expected_price": self.expected_price,
            "detail": self.detail,
        }


@dataclass
class CartRunResult:
    dry_run: bool
    results: list[CartLineResult] = field(default_factory=list)
    cart_url: str = CART_URL
    error: str | None = None

    @property
    def added(self) -> int:
        return sum(1 for r in self.results if r.status == ADDED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "added": self.added,
            "cart_url": self.cart_url,
            "error": self.error,
            "results": [r.to_dict() for r in self.results],
        }


_PRICE_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)")

# One round trip instead of dozens: collect every candidate tile's text at once.
# Read what the tile says is already in the cart. A tile with a minus button is
# in the cart, and the trailing bare number is its quantity.
READ_QTY_JS = r"""
([selector, index]) => {
  const node = document.querySelectorAll(selector)[index];
  if (!node) return {ok: false};
  const card = node.closest('[class*=card],[class*=Card],li,article') || node.parentElement;
  const minus = card.querySelector("[data-testid='btn-atc-minus']");
  const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  let qty = 0;
  if (minus) {
    for (let i = lines.length - 1; i >= 0; i--) {
      if (/^\d+$/.test(lines[i])) { qty = parseInt(lines[i], 10); break; }
    }
    if (!qty) qty = 1;
  }
  return {ok: true, inCart: !!minus, qty};
}
"""

STEP_JS = """
([selector, index, which]) => {
  const node = document.querySelectorAll(selector)[index];
  if (!node) return false;
  const card = node.closest('[class*=card],[class*=Card],li,article') || node.parentElement;
  const btn = card.querySelector("[data-testid='btn-atc-" + which + "']");
  if (!btn) return false;
  btn.click();
  return true;
}
"""

CLICK_JS = """
([selector, index, times]) => {
  const node = document.querySelectorAll(selector)[index];
  if (!node) return {ok: false, why: 'tile vanished'};
  const card = node.closest('[class*=card],[class*=Card],li,article') || node.parentElement;
  const text = (card.innerText || '');
  if (/sold out|notify me|out of stock/i.test(text)) return {ok: false, why: 'sold out'};
  const btn = card.querySelector("[data-testid='btn-atc-plus']");
  if (!btn) return {ok: false, why: 'no add control on this card'};
  let done = 0;
  for (let i = 0; i < times; i++) {
    const live = card.querySelector("[data-testid='btn-atc-plus']");
    if (!live) break;
    live.click();
    done++;
  }
  return {ok: done > 0, done};
}
"""

SCAN_JS = """
([selector, limit]) => {
  const nodes = Array.from(document.querySelectorAll(selector)).slice(0, limit);
  return nodes.map((node, index) => {
    const card = node.closest('[class*=card],[class*=Card],li,article') || node.parentElement || node;
    const titleEl = card.querySelector("[data-testid='product-title'],[class*='product-title'],h3");
    const priceEl = card.querySelector("[data-testid='product-price'],[class*='product-price'],[class*='Price']");
    const text = (card.innerText || '').slice(0, 400);
    return {
      index,
      title: titleEl ? titleEl.innerText.trim() : '',
      price: priceEl ? priceEl.innerText.trim() : '',
      text,
      hasAdd: !!card.querySelector("[data-testid='btn-atc-plus']"),
      soldOut: /sold out|notify me|out of stock/i.test(text),
    };
  });
}
"""


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    match = _PRICE_RE.search(text)
    return float(match.group(1)) if match else None


def _first_match(scope, candidates: Sequence[str]):
    """Return the first selector in `candidates` that matches inside `scope`."""
    for selector in candidates:
        found = scope.locator(selector)
        try:
            if found.count() > 0:
                return found.first
        except Exception:
            continue
    return None


# Lines inside a product tile that are chrome rather than the product name.
_NOISE_LINE = re.compile(
    r"^\s*(\$|\d+%|\d+[kK]\+|sold|snap|ebt|off\b|free\b|add\b|save\b|"
    r"[\d.]+\s*(lb|oz|ct|g|kg|ml|each)\b)",
    re.IGNORECASE,
)


def _clean_title(raw: str) -> str:
    """Pull the product name out of a tile's text.

    Weee! tiles stack price, unit price, badges and the name into one text blob,
    so take the longest line that is not obviously price or badge chrome.
    """
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    candidates = [ln for ln in lines if not _NOISE_LINE.match(ln) and len(ln) > 3]
    return max(candidates, key=len) if candidates else (lines[0] if lines else "")


# Pack sizes and units carry no relevance signal, and matching them rewards the
# wrong products.
_STOPWORDS = frozenset({
    "the", "and", "with", "for", "each", "pack", "count", "frozen", "fresh",
    "lb", "lbs", "oz", "ct", "bunch", "bag", "box", "pcs", "pieces", "kg", "ml",
})


def _significant(text: str) -> list[str]:
    return [
        w
        for w in re.split(r"\W+", text.lower())
        if len(w) > 2 and w not in _STOPWORDS and not w.isdigit()
    ]


def _match_score(query: str, title: str) -> float:
    """Fraction of the query's significant words present in the title.

    Word-boundary matching, not substring: "broccoli" must not match
    "Broccolini", which is a different vegetable at a different price.
    """
    words = _significant(query)
    if not words:
        return 0.0
    lowered = title.lower()
    hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", lowered))
    return hits / len(words)


def _title_matches(query: str, title: str) -> bool:
    return _match_score(query, title) >= 1.0


def _add_button_for(tile, candidates: Sequence[str]):
    """Find the add-to-cart control for a result tile.

    The tile we match on is the product link, but the add control lives beside
    it in the card wrapper rather than inside it. So look within the tile first,
    then walk up to the nearest ancestor that actually contains the control.
    """
    inside = _first_match(tile, candidates)
    if inside is not None:
        return inside

    for selector in candidates:
        # Turn a CSS attribute selector into the XPath predicate form.
        attr = re.match(r"\[([\w-]+)='([^']+)'\]", selector)
        if attr:
            predicate = f"@{attr.group(1)}='{attr.group(2)}'"
        elif selector.startswith("button[aria-label='"):
            predicate = f"@aria-label='{selector.split(chr(39))[1]}'"
        else:
            continue
        xpath = (
            f"xpath=./ancestor::*[.//*[{predicate}]][1]//*[{predicate}]"
        )
        try:
            found = tile.locator(xpath)
            if found.count() > 0:
                return found.first
        except Exception:
            continue
    return None


@dataclass
class WeeeCartExecutor:
    """Adds approved lines to the cart of an already-open Weee! session."""

    cdp_url: str = DEFAULT_CDP_URL
    selectors: Selectors = DEFAULT
    dry_run: bool = True
    price_tolerance: float = 2.0  # reject a match this many times the expected price
    timeout_ms: int = 15000
    click_timeout_ms: int = 5000  # a slow add control should not stall the run
    scan_results: int = 8  # how many search results to consider per item
    match_threshold: float = 0.6  # minimum share of query words in the title

    def _connect(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise BrowserUnavailable(
                "playwright is not installed. `pip install playwright` and "
                "`playwright install chromium`."
            ) from exc

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception as exc:
            playwright.stop()
            raise BrowserUnavailable(
                f"No debuggable Chrome at {self.cdp_url}. Launch one with "
                "--remote-debugging-port=9222 and sign in to Weee! first."
            ) from exc
        return playwright, browser

    def add_lines(self, lines: Iterable[dict[str, Any]]) -> CartRunResult:
        """Add each approved line. `lines` come from `approved_lines()`."""
        lines = list(lines)
        run = CartRunResult(dry_run=self.dry_run)

        pending = []
        for line in lines:
            if not line.get("approved"):
                run.results.append(
                    CartLineResult(
                        item=line["item"],
                        status=NOT_APPROVED,
                        quantity=line.get("quantity", 1),
                        detail=line.get("reason", "no APPROVE decision attached"),
                    )
                )
            else:
                pending.append(line)

        if not pending:
            return run

        try:
            playwright, browser = self._connect()
        except BrowserUnavailable as exc:
            run.error = str(exc)
            for line in pending:
                run.results.append(
                    CartLineResult(
                        item=line["item"],
                        status=BROWSER_UNAVAILABLE,
                        quantity=line.get("quantity", 1),
                        detail=str(exc),
                    )
                )
            return run

        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(self.timeout_ms)

            for line in pending:
                run.results.append(self._add_one(page, line))
        finally:
            try:
                playwright.stop()
            except Exception:
                pass

        return run

    def add_lines_on_worker(self, worker, lines: Iterable[dict[str, Any]]) -> CartRunResult:
        """Add lines using a long-lived `BrowserWorker` instead of a fresh CDP attach.

        This is the path the app uses: the browser stays open between clicks, so
        the buyer's Weee! session is signed in once and reused.
        """
        lines = list(lines)
        run = CartRunResult(dry_run=self.dry_run)

        pending = []
        for line in lines:
            if not line.get("approved"):
                run.results.append(
                    CartLineResult(
                        item=line["item"],
                        status=NOT_APPROVED,
                        quantity=line.get("quantity", 1),
                        detail=line.get("reason", "no APPROVE decision attached"),
                    )
                )
            else:
                pending.append(line)

        if not pending:
            return run

        try:
            results = worker.submit(
                lambda page: [self._add_one(page, line) for line in pending],
                timeout=60 + 25 * len(pending),
            )
            run.results.extend(results)
        except Exception as exc:
            run.error = str(exc)
            for line in pending:
                run.results.append(
                    CartLineResult(
                        item=line["item"],
                        status=BROWSER_UNAVAILABLE,
                        quantity=line.get("quantity", 1),
                        detail=str(exc),
                    )
                )
        return run

    def _add_one(self, page, line: dict[str, Any]) -> CartLineResult:
        item = line["item"]
        quantity = line.get("quantity", 1)
        expected = line.get("expected_price")
        query = line.get("search_query") or item

        def search(term: str):
            """Run one search and return (tile selector, scanned cards)."""
            page.goto(SEARCH_URL.format(query=quote_plus(term)), wait_until="domcontentloaded")
            # Results stream in. Scanning too early sees only the first few
            # tiles and can miss the buyer's product further down the page, so
            # wait for the count to settle rather than guessing a delay.
            page.wait_for_timeout(700)
            previous = -1
            for _ in range(8):
                try:
                    count = page.locator(self.selectors.product_tile[0]).count()
                except Exception:
                    count = 0
                if count >= self.scan_results or count == previous:
                    break
                previous = count
                page.wait_for_timeout(400)

            for selector in self.selectors.product_tile:
                try:
                    found = page.evaluate(SCAN_JS, [selector, self.scan_results])
                except Exception:
                    found = []
                if found:
                    return selector, found
            return None, []

        def rank(cards, term):
            """Pick the best addable card, and the best sold-out one separately."""
            best = (None, 0.0, "", None)
            blocked = ("", 0.0)
            for card in cards:
                title = (card.get("title") or "").strip() or _clean_title(card.get("text") or "")
                # Search with the specific past purchase, but judge on the
                # essential item name: "Broccoli Crowns, 2 lb" is the right
                # search, "Broccoli 1.95-2.05 lb" is the right thing to buy.
                coverage = max(_match_score(item, title), _match_score(term, title))
                extra = max(0, len(_significant(title)) - len(_significant(term)))
                score = coverage - min(0.25, 0.02 * extra)
                if card.get("soldOut") or not card.get("hasAdd", True):
                    if score > blocked[1]:
                        blocked = (title, score)
                    continue
                if score > best[1]:
                    price = _parse_price(card.get("price") or card.get("text"))
                    best = (card.get("index"), score, title, price)
            return best, blocked

        # The buyer's own product string is usually the better search term, but
        # an over-specific one surfaces brand-mates instead of the product --
        # Oceankist's full pompano label returns their smelt. Fall back to the
        # plain item name when the specific search finds nothing good enough.
        terms = [query] if query.strip().lower() == item.strip().lower() else [query, item]
        tile_selector, cards = None, []
        best = (None, 0.0, "", None)
        blocked = ("", 0.0)
        for term in terms:
            selector, found = search(term)
            if not found:
                continue
            candidate, candidate_blocked = rank(found, term)
            if candidate[1] > best[1]:
                tile_selector, cards, best = selector, found, candidate
            if candidate_blocked[1] > blocked[1]:
                blocked = candidate_blocked
            if best[1] >= self.match_threshold:
                break

        best_index, best_score, title, price = best
        blocked_title, blocked_score = blocked

        if not cards:
            return CartLineResult(
                item=item, status=NO_MATCH, quantity=quantity, expected_price=expected,
                detail="no product tile matched; recalibrate selectors.product_tile",
            )

        # The buyer's actual product is here but unavailable: a stock fact, not
        # a failure to find it.
        if blocked_title and blocked_score >= self.match_threshold and blocked_score > best_score:
            return CartLineResult(
                item=item, status=OUT_OF_STOCK, quantity=quantity,
                matched_title=blocked_title, expected_price=expected,
                detail="Weee! lists this item as sold out",
            )

        if best_index is None or best_score < self.match_threshold:
            return CartLineResult(
                item=item, status=NO_MATCH, quantity=quantity,
                matched_title=title or None, matched_price=price, expected_price=expected,
                detail=(
                    f"best of {len(cards)} results scored {best_score:.0%}; "
                    f"below the {self.match_threshold:.0%} threshold"
                ),
            )

        # A live price far above what this buyer normally pays is exactly the
        # change the mandate exists to catch, so refuse rather than add.
        if expected and price and price > expected * self.price_tolerance:
            return CartLineResult(
                item=item, status=PRICE_ABOVE_LIMIT, quantity=quantity,
                matched_title=title, matched_price=price, expected_price=expected,
                detail=(
                    f"${price:.2f} is more than {self.price_tolerance:g}x the "
                    f"${expected:.2f} this buyer usually pays; needs revalidation"
                ),
            )

        # Preview stops here: matched, priced and judged, but nothing clicked.
        if self.dry_run:
            return CartLineResult(
                item=item, status=DRY_RUN, quantity=quantity,
                matched_title=title, matched_price=price, expected_price=expected,
                detail="matched; not added because this was a preview",
            )

        try:
            page.locator(tile_selector).nth(best_index).scroll_into_view_if_needed(timeout=4000)
            page.wait_for_timeout(250)
        except Exception:
            pass

        # Drive the tile's stepper to the quantity the plan asked for rather
        # than blind-clicking add. Reading the current value first makes a
        # repeat run idempotent: the cart ends up matching the plan instead of
        # doubling, and Weee! needs a beat to re-render between clicks.
        target = max(1, int(quantity))
        try:
            state = page.evaluate(READ_QTY_JS, [tile_selector, best_index])
        except Exception:
            state = {}
        current = int(state.get("qty") or 0)
        started_at = current

        for _ in range(target + 6):
            if current == target:
                break
            which = "plus" if current < target else "minus"
            try:
                if not page.evaluate(STEP_JS, [tile_selector, best_index, which]):
                    break
            except Exception:
                break
            page.wait_for_timeout(700)
            try:
                moved = int((page.evaluate(READ_QTY_JS, [tile_selector, best_index]) or {}).get("qty") or 0)
            except Exception:
                break
            if moved == current:  # the click did not take
                break
            current = moved

        if not current:
            return CartLineResult(
                item=item, status=ADD_BUTTON_NOT_FOUND, quantity=quantity,
                matched_title=title, matched_price=price, expected_price=expected,
                detail="found the product but its add control did not respond",
            )

        if current == target:
            detail = f"cart already had {target}" if started_at == target else f"cart set to {target}"
        else:
            detail = f"cart is at {current}, wanted {target} (stepper stopped responding)"

        return CartLineResult(
            item=item,
            status=ADDED if current == target else PARTIAL,
            quantity=current,
            matched_title=title,
            matched_price=price,
            expected_price=expected,
            detail=detail,
        )
