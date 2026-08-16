"""Curated pairwise trade-offs for cold-start preference learning."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from user_profile.product import Product

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
COMPARISON_PAIRS_PATH = FIXTURES_DIR / "comparison_pairs.json"
MAYA_COMPARISONS_PATH = FIXTURES_DIR / "maya_comparisons.json"

TRUSTED_MERCHANTS = frozenset({"MandateMart"})

AXES_FOR_TRADEOFF: dict[str, frozenset[str]] = {
    "price_vs_quality": frozenset({"price", "quality"}),
    "brand_vs_price": frozenset({"brand", "price"}),
    "delivery_vs_price": frozenset({"delivery", "price"}),
    "new_vs_refurbished": frozenset({"condition"}),
    "returns_vs_price": frozenset({"returns", "price"}),
    "brand_vs_brand": frozenset({"brand"}),
    "merchant_trust_vs_price": frozenset({"merchant", "price"}),
    "quality_vs_brand": frozenset({"quality", "brand"}),
}


class ComparisonChoice(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    EITHER = "EITHER"
    NEITHER = "NEITHER"


@dataclass(frozen=True)
class ComparisonPair:
    pair_id: str
    tradeoff: str
    prompt: str
    left: Product
    right: Product

    def product_for(self, side: str) -> Product:
        if side == "left":
            return self.left
        if side == "right":
            return self.right
        raise KeyError(side)

    def to_dict(self) -> dict[str, object]:
        return {
            "pair_id": self.pair_id,
            "tradeoff": self.tradeoff,
            "prompt": self.prompt,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


@dataclass(frozen=True)
class ComparisonResponse:
    pair_id: str
    choice: ComparisonChoice


@dataclass(frozen=True)
class ComparisonCatalog:
    category: str
    demo_pair_count: int
    pairs: tuple[ComparisonPair, ...]

    def pair_map(self) -> dict[str, ComparisonPair]:
        return {pair.pair_id: pair for pair in self.pairs}

    def demo_pairs(self) -> tuple[ComparisonPair, ...]:
        return self.pairs[: self.demo_pair_count]

    def products(self) -> list[Product]:
        seen: dict[str, Product] = {}
        for pair in self.pairs:
            seen.setdefault(pair.left.id, pair.left)
            seen.setdefault(pair.right.id, pair.right)
        return list(seen.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "demo_pair_count": self.demo_pair_count,
            "pairs": [pair.to_dict() for pair in self.pairs],
        }


def _load_pair(raw: dict[str, object]) -> ComparisonPair:
    left = raw["left"]
    right = raw["right"]
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise TypeError("comparison pair sides must be objects")
    return ComparisonPair(
        pair_id=str(raw["pair_id"]),
        tradeoff=str(raw["tradeoff"]),
        prompt=str(raw["prompt"]),
        left=Product.from_dict(left),
        right=Product.from_dict(right),
    )


def load_comparison_catalog(path: str | Path | None = None) -> ComparisonCatalog:
    target = Path(path) if path is not None else COMPARISON_PAIRS_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    pairs = tuple(_load_pair(item) for item in payload["pairs"])
    return ComparisonCatalog(
        category=str(payload.get("category") or "headphones"),
        demo_pair_count=int(payload.get("demo_pair_count") or len(pairs)),
        pairs=pairs,
    )


def load_comparison_pairs(path: str | Path | None = None) -> tuple[ComparisonPair, ...]:
    return load_comparison_catalog(path).pairs


def parse_comparison_responses(
    items: Sequence[dict[str, str] | ComparisonResponse],
) -> list[ComparisonResponse]:
    responses: list[ComparisonResponse] = []
    for item in items:
        if isinstance(item, ComparisonResponse):
            responses.append(item)
            continue
        responses.append(
            ComparisonResponse(
                pair_id=str(item["pair_id"]),
                choice=ComparisonChoice(item["choice"]),
            )
        )
    return responses


def load_maya_comparisons(
    path: str | Path | None = None,
) -> tuple[str, str, list[ComparisonResponse]]:
    target = Path(path) if path is not None else MAYA_COMPARISONS_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    return (
        str(payload["buyer_id"]),
        str(payload.get("category") or "headphones"),
        parse_comparison_responses(payload["comparisons"]),
    )


def observations_from_comparisons(
    responses: Sequence[ComparisonResponse],
    pairs: dict[str, ComparisonPair],
) -> list[tuple[Product, bool]]:
    """Turn pairwise choices into accept/reject labels for the Bayesian model."""
    observations: list[tuple[Product, bool]] = []
    for response in responses:
        pair = pairs.get(response.pair_id)
        if pair is None:
            continue
        if response.choice is ComparisonChoice.LEFT:
            observations.append((pair.left, True))
            observations.append((pair.right, False))
        elif response.choice is ComparisonChoice.RIGHT:
            observations.append((pair.left, False))
            observations.append((pair.right, True))
        elif response.choice is ComparisonChoice.EITHER:
            observations.append((pair.left, True))
            observations.append((pair.right, True))
        else:
            observations.append((pair.left, False))
            observations.append((pair.right, False))
    return observations


def unknown_product_ids(
    product_ids: Sequence[str],
    catalog: ComparisonCatalog,
) -> list[str]:
    known = {product.id for product in catalog.products()}
    seen: set[str] = set()
    unknown: list[str] = []
    for item_id in product_ids:
        if item_id in known or item_id in seen:
            continue
        seen.add(item_id)
        unknown.append(item_id)
    return unknown


def comparisons_from_rejected_ids(
    rejected_ids: Sequence[str],
    catalog: ComparisonCatalog,
) -> list[ComparisonResponse]:
    """Map item-level nos onto LEFT/RIGHT/NEITHER for the profile builder."""
    rejected = set(rejected_ids)
    responses: list[ComparisonResponse] = []
    for pair in catalog.pairs:
        left_no = pair.left.id in rejected
        right_no = pair.right.id in rejected
        if left_no and right_no:
            choice = ComparisonChoice.NEITHER
        elif left_no:
            choice = ComparisonChoice.RIGHT
        elif right_no:
            choice = ComparisonChoice.LEFT
        else:
            continue
        responses.append(ComparisonResponse(pair_id=pair.pair_id, choice=choice))
    return responses


def observations_from_rejected_ids(
    rejected_ids: Sequence[str],
    catalog: ComparisonCatalog,
) -> list[tuple[Product, bool]]:
    """Label every catalog product: rejected is no, remaining is kept."""
    rejected = set(rejected_ids)
    return [(product, product.id not in rejected) for product in catalog.products()]
