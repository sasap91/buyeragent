from user_profile.comparisons import (
    ComparisonCatalog,
    ComparisonChoice,
    ComparisonPair,
    ComparisonResponse,
    load_comparison_catalog,
    load_comparison_pairs,
    load_maya_comparisons,
)
from user_profile.contract import ColdStartProfileBuilder, to_contract_profile
from user_profile.csv_io import load_products, load_users
from user_profile.objectives import ObjectiveScores, score_catalog, score_product
from user_profile.pareto import CurvePoint, ParetoCurve, dominates, filter_feed
from user_profile.preferences import PREFERENCE_AXES, User, UserPreferences
from user_profile.product import Product
from user_profile.utility import UtilityFunction


def __getattr__(name: str):
    """Load the scientific model only when a caller actually requests it."""

    if name == "UserPreferenceModel":
        from user_profile.user_preference_model import UserPreferenceModel

        return UserPreferenceModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "PREFERENCE_AXES",
    "ColdStartProfileBuilder",
    "ComparisonCatalog",
    "ComparisonChoice",
    "ComparisonPair",
    "ComparisonResponse",
    "CurvePoint",
    "ObjectiveScores",
    "ParetoCurve",
    "Product",
    "User",
    "UserPreferenceModel",
    "UserPreferences",
    "UtilityFunction",
    "dominates",
    "filter_feed",
    "load_comparison_catalog",
    "load_comparison_pairs",
    "load_maya_comparisons",
    "load_products",
    "load_users",
    "score_catalog",
    "score_product",
    "to_contract_profile",
]
