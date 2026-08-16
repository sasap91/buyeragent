from collections.abc import Sequence
from dataclasses import dataclass, field

from user_profile.objectives import ObjectiveScores, score_catalog, score_product
from user_profile.preferences import PREFERENCE_AXES, User
from user_profile.product import Product
from user_profile.utility import UtilityFunction


def dominates(left: ObjectiveScores, right: ObjectiveScores) -> bool:
    """True if `left` is at least as good on every axis and strictly better on one."""
    left_vec = left.as_vector()
    right_vec = right.as_vector()
    return all(a >= b for a, b in zip(left_vec, right_vec)) and any(
        a > b for a, b in zip(left_vec, right_vec)
    )


@dataclass(frozen=True)
class CurvePoint:
    x: float
    y: float
    product_id: str


@dataclass
class ParetoCurve:
    user: User
    products: tuple[Product, ...]
    scores: dict[str, ObjectiveScores]
    catalog: tuple[Product, ...] = field(default_factory=tuple)

    @classmethod
    def from_catalog(cls, user: User, products: Sequence[Product]) -> "ParetoCurve":
        catalog = tuple(products)
        eligible = [p for p in catalog if user.preferences.passes_hard_filters(p)]
        scores = score_catalog(user, catalog)
        front: list[Product] = []
        for product in eligible:
            product_scores = scores[product.id]
            if any(
                other.id != product.id and dominates(scores[other.id], product_scores)
                for other in eligible
            ):
                continue
            front.append(product)
        return cls(user=user, products=tuple(front), scores=scores, catalog=catalog)

    def is_on_front(self, product: Product) -> bool:
        return any(item.id == product.id for item in self.products)

    def projection(
        self,
        x_axis: str = "price",
        y_axis: str = "quality",
    ) -> tuple[CurvePoint, ...]:
        """2D Pareto staircase: sort by x, keep points that improve y."""
        if x_axis not in PREFERENCE_AXES or y_axis not in PREFERENCE_AXES:
            raise ValueError(f"axes must be one of {PREFERENCE_AXES}")
        points = [
            (self.scores[product.id].as_dict()[x_axis],
             self.scores[product.id].as_dict()[y_axis],
             product.id)
            for product in self.products
            if product.id in self.scores
        ]
        points.sort(key=lambda item: (item[0], -item[1]))
        staircase: list[CurvePoint] = []
        best_y = float("-inf")
        for x, y, product_id in points:
            if y > best_y:
                staircase.append(CurvePoint(x=x, y=y, product_id=product_id))
                best_y = y
        return tuple(staircase)

    def is_below_curve(
        self,
        product: Product,
        x_axis: str = "price",
        y_axis: str = "quality",
    ) -> bool:
        """True if some 2D staircase point strictly dominates this product."""
        if x_axis not in PREFERENCE_AXES or y_axis not in PREFERENCE_AXES:
            raise ValueError(f"axes must be one of {PREFERENCE_AXES}")
        scores = self.scores.get(product.id)
        if scores is None:
            catalog = self.catalog or self.products
            scores = score_product(self.user, product, catalog)
        values = scores.as_dict()
        x, y = values[x_axis], values[y_axis]
        for point in self.projection(x_axis, y_axis):
            if point.x >= x and point.y >= y and (point.x > x or point.y > y):
                return True
        return False


def filter_feed(
    user: User,
    products: Sequence[Product],
    utility: UtilityFunction | None = None,
) -> list[Product]:
    """Hard-filter, keep the Pareto set, then rank by P(buy)."""
    utility = utility or UtilityFunction()
    curve = ParetoCurve.from_catalog(user, products)
    return sorted(
        curve.products,
        key=lambda product: utility.buy_probability(user, product, products),
        reverse=True,
    )
