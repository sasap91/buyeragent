"""FastAPI router expected by the cold-start comparison frontend."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mandatelab_contracts import BuyerPreferenceProfile
from user_profile.contract import (
    ColdStartProfileBuilder,
    profile_input_from_model,
)
from user_profile.csv_io import load_products


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPOSITORY_ROOT / "user_profile" / "examples" / "products.csv"


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelUpdateRequest(ApiModel):
    remaining_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    buyer_id: str = "cold-start-demo"
    category: str = "*"

    @model_validator(mode="after")
    def ids_must_be_unique_and_disjoint(self):
        if len(set(self.remaining_ids)) != len(self.remaining_ids):
            raise ValueError("remaining_ids must be unique")
        if len(set(self.rejected_ids)) != len(self.rejected_ids):
            raise ValueError("rejected_ids must be unique")
        overlap = set(self.remaining_ids) & set(self.rejected_ids)
        if overlap:
            raise ValueError("remaining_ids and rejected_ids must be disjoint")
        return self


class WeightRow(ApiModel):
    name: str
    value: float


class PlotSnapshot(ApiModel):
    quality_price: str
    price_sustainability: str


class ModelUpdateResponse(ApiModel):
    weights: list[WeightRow]
    plots: PlotSnapshot
    profile: BuyerPreferenceProfile


def _encode_plot(axis) -> str:
    import matplotlib.pyplot as plt

    buffer = BytesIO()
    axis.figure.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(axis.figure)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def build_update_snapshot(request: ModelUpdateRequest) -> ModelUpdateResponse:
    """Fit Luke's model and expose both its UI snapshot and shared contract."""

    catalog = load_products(CATALOG_PATH)
    by_id = {product.id: product for product in catalog}
    supplied = set(request.remaining_ids) | set(request.rejected_ids)
    unknown = sorted(supplied - set(by_id))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown product ids: {', '.join(unknown)}",
        )

    from user_profile.user_preference_model import UserPreferenceModel

    observations = [
        (by_id[product_id], True) for product_id in request.remaining_ids
    ]
    observations.extend(
        (by_id[product_id], False) for product_id in request.rejected_ids
    )
    model = UserPreferenceModel(catalog)
    model.fit(observations)
    has_contrast = bool(request.remaining_ids and request.rejected_ids)
    evidence = profile_input_from_model(
        model,
        catalog,
        buyer_id=request.buyer_id,
        category=request.category,
        observation_count=len(observations) if has_contrast else 0,
        created_at=datetime.now(timezone.utc),
    )
    profile = ColdStartProfileBuilder().build_profile(evidence)
    labels = {
        **{product_id: True for product_id in request.remaining_ids},
        **{product_id: False for product_id in request.rejected_ids},
    }
    return ModelUpdateResponse(
        weights=[WeightRow.model_validate(row) for row in model.weights()],
        plots=PlotSnapshot(
            quality_price=_encode_plot(
                model.plot_decision_boundary(
                    "price", "quality", labels=labels
                )
            ),
            price_sustainability=_encode_plot(
                model.plot_decision_boundary(
                    "sustainability", "price", labels=labels
                )
            ),
        ),
        profile=profile,
    )


router = APIRouter()


@router.post("/api/update", response_model=ModelUpdateResponse)
def update_model(request: ModelUpdateRequest) -> ModelUpdateResponse:
    return build_update_snapshot(request)


def main() -> None:
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="MandateLab cold-start profile")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
