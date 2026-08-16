import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from user_profile import ParetoCurve, UtilityFunction, filter_feed
from user_profile.csv_io import load_products, load_users

EXAMPLES = Path(__file__).resolve().parent


def main() -> None:
    products = load_products(EXAMPLES / "products.csv")
    users = load_users(EXAMPLES / "users.csv")
    utility = UtilityFunction()
    for user in users:
        print(f"=== {user.name} ===")
        prefs = user.preferences
        print(
            "weights: "
            f"price={prefs.price_weight:.2f} "
            f"quality={prefs.quality_weight:.2f} "
            f"brand={prefs.brand_weight:.2f} "
            f"sustainability={prefs.sustainability_weight:.2f}"
        )
        if prefs.max_price is not None:
            print(f"max_price={prefs.max_price:.0f}")
        if prefs.min_quality is not None:
            print(f"min_quality={prefs.min_quality:.2f}")

        curve = ParetoCurve.from_catalog(user, products)
        dropped = len(products) - len(curve.products)
        print(f"pareto set: {len(curve.products)} of {len(products)} (dropped {dropped})")

        projection = curve.projection("price", "quality")
        print("price vs quality curve:")
        for point in projection:
            print(f"  {point.product_id}: price={point.x:.2f} quality={point.y:.2f}")

        feed = filter_feed(user, products, utility)
        print("filtered feed (ranked by P(buy)):")
        for product in feed:
            p_buy = utility.buy_probability(user, product, products)
            will_buy = utility.will_buy(user, product, products)
            print(
                f"  {product.name:32} ${product.price:6.2f}  "
                f"P(buy)={p_buy:.3f}  will_buy={will_buy}"
            )
        print()


if __name__ == "__main__":
    main()
