"""Cold-start HTTP routes, mounted on the MandateLab API at `/api/update`."""

from __future__ import annotations

import base64
import io

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from mandatelab_contracts import BuyerPreferenceProfile

from user_profile.comparisons import (
    ComparisonChoice,
    ComparisonResponse,
    load_comparison_catalog,
    observations_from_comparisons,
)
from user_profile.contract import ColdStartProfileBuilder

router = APIRouter(tags=["cold-start"])

_CATALOG = load_comparison_catalog()


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComparisonResponseBody(ApiModel):
    pair_id: str = Field(min_length=1)
    choice: ComparisonChoice


class UpdateRequest(ApiModel):
    buyer_id: str = "buyer-maya"
    category: str | None = None
    comparisons: list[ComparisonResponseBody] = Field(default_factory=list)
    include_model: bool = True


class WeightRow(ApiModel):
    name: str
    value: float


class ModelPlots(ApiModel):
    quality_price: str
    price_sustainability: str


class UpdateResponse(ApiModel):
    profile: BuyerPreferenceProfile
    weights: list[WeightRow] = Field(default_factory=list)
    plots: ModelPlots | None = None


def _figure_to_base64(axes) -> str:
    buffer = io.BytesIO()
    axes.figure.savefig(buffer, format="png", bbox_inches="tight")
    from matplotlib import pyplot as plt

    plt.close(axes.figure)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _model_snapshot(
    responses: list[ComparisonResponse],
) -> tuple[list[WeightRow], ModelPlots | None]:
    import matplotlib

    matplotlib.use("Agg", force=True)

    from user_profile.user_preference_model import UserPreferenceModel

    catalog = _CATALOG.products()
    if not catalog:
        return [], None

    model = UserPreferenceModel(catalog)
    observations = observations_from_comparisons(responses, _CATALOG.pair_map())
    if observations:
        model.fit(observations)

    labels = {product.id: bought for product, bought in observations}
    quality_price = _figure_to_base64(
        model.plot_decision_boundary(
            x_axis="price",
            y_axis="quality",
            labels=labels or None,
        )
    )
    price_sustainability = _figure_to_base64(
        model.plot_decision_boundary(
            x_axis="price",
            y_axis="sustainability",
            labels=labels or None,
        )
    )
    weights = [
        WeightRow(name=str(row["name"]), value=float(row["value"]))
        for row in model.weights()
    ]
    return weights, ModelPlots(
        quality_price=quality_price,
        price_sustainability=price_sustainability,
    )


@router.get("/api/pairs")
def get_pairs() -> dict[str, object]:
    return _CATALOG.to_dict()


@router.post("/api/update", response_model=UpdateResponse)
def update_profile(request: UpdateRequest) -> UpdateResponse:
    responses = [
        ComparisonResponse(pair_id=item.pair_id, choice=item.choice)
        for item in request.comparisons
    ]
    unknown = [item.pair_id for item in responses if item.pair_id not in _CATALOG.pair_map()]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown comparison pair(s): {', '.join(unknown)}",
        )

    builder = ColdStartProfileBuilder(
        buyer_id=request.buyer_id,
        category=request.category,
        catalog=_CATALOG,
    )
    profile = builder.build_profile(responses)

    weights: list[WeightRow] = []
    plots: ModelPlots | None = None
    if request.include_model:
        try:
            weights, plots = _model_snapshot(responses)
        except Exception:
            weights, plots = [], None

    return UpdateResponse(profile=profile, weights=weights, plots=plots)


def create_standalone_app():
    from fastapi import FastAPI

    application = FastAPI(
        title="MandateLab Cold-Start",
        version="0.1.0",
        description="Standalone cold-start router. Prefer mounting on mandatelab-api.",
    )
    application.include_router(router)
    return application


standalone_app = create_standalone_app()
