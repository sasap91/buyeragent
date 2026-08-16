from collections.abc import Sequence
from math import exp

from user_profile.objectives import score_product
from user_profile.preferences import User
from user_profile.product import Product


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


class UtilityFunction:
    """Predicts P(buy) from a weighted sum of user-specific objective scores."""

    def __init__(self, scale: float = 6.0, bias: float = -0.5) -> None:
        self.scale = scale
        self.bias = bias

    def score(
        self,
        user: User,
        product: Product,
        catalog: Sequence[Product] | None = None,
    ) -> float:
        catalog = list(catalog) if catalog is not None else [product]
        objectives = score_product(user, product, catalog)
        weights = user.preferences.normalized_weights()
        return (
            weights["price"] * objectives.price
            + weights["quality"] * objectives.quality
            + weights["brand"] * objectives.brand
            + weights["sustainability"] * objectives.sustainability
        )

    def buy_probability(
        self,
        user: User,
        product: Product,
        catalog: Sequence[Product] | None = None,
    ) -> float:
        utility = self.score(user, product, catalog)
        return _sigmoid(self.scale * (utility + self.bias))

    def will_buy(
        self,
        user: User,
        product: Product,
        catalog: Sequence[Product] | None = None,
        threshold: float = 0.5,
    ) -> bool:
        return self.buy_probability(user, product, catalog) >= threshold
