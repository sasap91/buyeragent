from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

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


def _catalog_mean_variance(values: Sequence[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    return mean, variance


def _z_score(value: float, values: Sequence[float]) -> float:
    mean, variance = _catalog_mean_variance(values)
    if variance <= 0:
        return 0.0
    return (value - mean) / sqrt(variance)


def _price_score(product: Product, catalog: Sequence[Product]) -> float:
    """Z-score of price vs the catalog; negated so cheaper is better."""
    if not catalog:
        return 0.0
    return -_z_score(product.price, [item.price for item in catalog])


def _quality_score(product: Product, catalog: Sequence[Product]) -> float:
    """Z-score of quality vs the catalog; higher quality is better."""
    if not catalog:
        return 0.0
    return _z_score(product.quality, [item.quality for item in catalog])


def score_product(
    user: User,
    product: Product,
    catalog: Sequence[Product],
) -> ObjectiveScores:
    return ObjectiveScores(
        price=_price_score(product, catalog),
        quality=_quality_score(product, catalog),
        brand=user.preferences.brand_affinity(product.brand),
        sustainability=product.sustainability,
    )


def score_catalog(user: User, products: Sequence[Product]) -> dict[str, ObjectiveScores]:
    return {product.id: score_product(user, product, products) for product in products}
