from dataclasses import dataclass, field

from user_profile.product import Product

PREFERENCE_AXES = ("price", "quality", "brand", "sustainability")


@dataclass
class UserPreferences:
    price_weight: float = 0.25
    quality_weight: float = 0.25
    brand_weight: float = 0.25
    sustainability_weight: float = 0.25
    brand_affinities: dict[str, float] = field(default_factory=dict)
    max_price: float | None = None
    min_quality: float | None = None

    def weights(self) -> dict[str, float]:
        return {
            "price": self.price_weight,
            "quality": self.quality_weight,
            "brand": self.brand_weight,
            "sustainability": self.sustainability_weight,
        }

    def normalized_weights(self) -> dict[str, float]:
        raw = self.weights()
        total = sum(raw.values())
        if total <= 0:
            n = len(raw)
            return {axis: 1.0 / n for axis in raw}
        return {axis: weight / total for axis, weight in raw.items()}

    def brand_affinity(self, brand: str) -> float:
        value = self.brand_affinities.get(brand, 0.0)
        return min(1.0, max(0.0, value))

    def passes_hard_filters(self, product: Product) -> bool:
        if self.max_price is not None and product.price > self.max_price:
            return False
        if self.min_quality is not None and product.quality < self.min_quality:
            return False
        return True


@dataclass
class User:
    id: str
    name: str
    preferences: UserPreferences
