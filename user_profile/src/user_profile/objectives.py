from collections.abc import Sequence
from dataclasses import dataclass

from user_profile.preferences import User
from user_profile.product import Product


@dataclass(frozen=True)
class ObjectiveScores:
    """User-specific scores; higher is better on every axis."""

    price: float
    quality: float
    brand: float
    sustainability: float

    def as_vector(self) -> tuple[float, float, float, float]:
        return (self.price, self.quality, self.brand, self.sustainability)

    def as_dict(self) -> dict[str, float]:
        return {
            "price": self.price,
            "quality": self.quality,
            "brand": self.brand,
            "sustainability": self.sustainability,
        }


def _price_score(
    product: Product,
    catalog: Sequence[Product],
    max_price: float | None,
) -> float:
    if not catalog:
        return 1.0
    prices = [item.price for item in catalog]
    lo = min(prices)
    hi = max_price if max_price is not None else max(prices)
    span = hi - lo
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (hi - product.price) / span))


def score_product(
    user: User,
    product: Product,
    catalog: Sequence[Product],
) -> ObjectiveScores:
    return ObjectiveScores(
        price=_price_score(product, catalog, user.preferences.max_price),
        quality=product.quality,
        brand=user.preferences.brand_affinity(product.brand),
        sustainability=product.sustainability,
    )


def score_catalog(user: User, products: Sequence[Product]) -> dict[str, ObjectiveScores]:
    return {product.id: score_product(user, product, products) for product in products}
