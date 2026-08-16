from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import combinations, product as cartesian_product
from math import exp, sqrt

import matplotlib.pyplot as plt
import numpy as np
import pyro
import pyro.distributions as dist
import torch
from matplotlib.axes import Axes
from pyro.infer import SVI, Trace_ELBO
from pyro.infer.autoguide import AutoNormal, init_to_mean
from pyro.optim import Adam

from user_profile.objectives import _z_score
from user_profile.product import Product

MAIN_FIELDS = ("category", "brand", "price", "quality", "sustainability")
NUMERIC_FIELDS = frozenset({"price", "quality", "sustainability"})
CATEGORICAL_FIELDS = frozenset({"category", "brand"})
TRIPLET_FIELDS = ("category", "brand", "price", "quality")

INTERACTIONS: tuple[tuple[str, ...], ...] = (
    *((field,) for field in MAIN_FIELDS),
    *combinations(MAIN_FIELDS, 2),
    *combinations(TRIPLET_FIELDS, 3),
)

PRIOR_PRECISION = {0: 0.25, 1: 1.0, 2: 4.0, 3: 16.0}
_SVI_STEPS = 500
_SVI_LR = 0.05
_GRID_SIZE = 50
_BOUNDARY_Z = 1.96
_POINT_COLORS = {True: "#2ecc71", False: "#e74c3c"}


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _prior_scale(order: int) -> float:
    return 1.0 / sqrt(PRIOR_PRECISION[order])


def logistic_model(
    x: torch.Tensor,
    y: torch.Tensor | None = None,
    prior_scale: torch.Tensor | None = None,
) -> None:
    n, d = x.shape
    assert prior_scale is not None
    bias = pyro.sample("bias", dist.Normal(0.0, prior_scale[0]))
    with pyro.plate("coefficients", d):
        weights = pyro.sample("weights", dist.Normal(0.0, prior_scale[1:]))
    logits = bias + (x @ weights if d else bias.new_zeros(n))
    with pyro.plate("data", n):
        pyro.sample("obs", dist.Bernoulli(logits=logits), obs=y)


class UserPreferenceModel:
    """Bayesian logistic P(buy) from product features, fit with Pyro SVI."""

    def __init__(self, catalog: Sequence[Product]) -> None:
        self._catalog = tuple(catalog)
        self._numeric_refs = {
            field: [getattr(item, field) for item in self._catalog]
            for field in NUMERIC_FIELDS
        }
        self._categorical_values = {
            field: tuple(sorted({getattr(item, field) for item in self._catalog}))
            for field in CATEGORICAL_FIELDS
        }
        keys: list[str] = []
        seen: set[str] = set()
        for item in self._catalog:
            for key, value in self.features(item).items():
                if value == 0.0 or key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        self._feature_keys = tuple(keys)
        self._prior_scale = torch.tensor(
            [_prior_scale(0)] + [_prior_scale(key.count("*") + 1) for key in self._feature_keys],
            dtype=torch.float32,
        )
        self._reset_prior()

    def _atom_encodings(self, product: Product, field: str) -> list[tuple[str, float]]:
        if field in NUMERIC_FIELDS:
            z = _z_score(getattr(product, field), self._numeric_refs[field])
            return [(field, z)]
        return [
            (f"{field}={value}", 1.0 if getattr(product, field) == value else 0.0)
            for value in self._categorical_values[field]
        ]

    def features(self, product: Product) -> dict[str, float]:
        encoded: dict[str, float] = {}
        for fields in INTERACTIONS:
            parts = [self._atom_encodings(product, field) for field in fields]
            for combo in cartesian_product(*parts):
                key = "*".join(name for name, _ in combo)
                value = 1.0
                for _, part in combo:
                    value *= part
                encoded[key] = value
        return encoded

    def _feature_vector(self, product: Product) -> torch.Tensor:
        phi = self.features(product)
        return torch.tensor(
            [phi.get(key, 0.0) for key in self._feature_keys],
            dtype=torch.float32,
        )

    def value(self, product: Product) -> float:
        return float(self._bias + torch.dot(self._weights, self._feature_vector(product)))

    def buy_probability(self, product: Product) -> float:
        return _sigmoid(self.value(product))

    def _reset_prior(self) -> None:
        self._bias = 0.0
        self._weights = torch.zeros(len(self._feature_keys), dtype=torch.float32)
        self._bias_scale = float(self._prior_scale[0])
        self._weight_scales = (
            self._prior_scale[1:].clone()
            if self._prior_scale.numel() > 1
            else torch.zeros(0, dtype=torch.float32)
        )

    def _logit_moments(self, phi: torch.Tensor) -> tuple[float, float]:
        mean = float(self._bias + torch.dot(self._weights, phi))
        variance = self._bias_scale**2 + float(torch.dot(self._weight_scales**2, phi**2))
        return mean, sqrt(max(variance, 0.0))

    def weights(self) -> list[dict[str, float | str]]:
        rows: list[tuple[str, float]] = [
            ("intercept", self._bias),
            *zip(self._feature_keys, self._weights.tolist(), strict=True),
        ]
        rows.sort(key=lambda item: abs(item[1]), reverse=True)
        return [{"name": name, "value": float(value)} for name, value in rows]

    def print_weights(self) -> None:
        rows = self.weights()
        width = max(len(str(row["name"])) for row in rows)
        for row in rows:
            print(f"{row['name']:<{width}}  {row['value']: .4f}")

    def _axis_range(self, field: str) -> tuple[float, float]:
        values = [float(getattr(item, field)) for item in self._catalog]
        lo, hi = min(values), max(values)
        pad = 0.1 * (hi - lo) if hi > lo else 0.1
        lo, hi = lo - pad, hi + pad
        if field in {"quality", "sustainability"}:
            return max(0.0, lo), min(1.0, hi)
        return max(0.0, lo), hi

    def plot_decision_boundary(
        self,
        x_axis: str = "price",
        y_axis: str = "quality",
        product: Product | None = None,
        labels: Mapping[str, bool] | None = None,
    ) -> Axes:
        if x_axis not in NUMERIC_FIELDS or y_axis not in NUMERIC_FIELDS:
            raise ValueError(f"axes must be one of {sorted(NUMERIC_FIELDS)}")
        if x_axis == y_axis:
            raise ValueError("x_axis and y_axis must differ")
        if not self._catalog:
            raise ValueError("catalog is empty")

        reference = product or self._catalog[0]
        x_lo, x_hi = self._axis_range(x_axis)
        y_lo, y_hi = self._axis_range(y_axis)
        xs = np.linspace(x_lo, x_hi, _GRID_SIZE)
        ys = np.linspace(y_lo, y_hi, _GRID_SIZE)
        mean_logits = np.zeros((_GRID_SIZE, _GRID_SIZE))
        std_logits = np.zeros((_GRID_SIZE, _GRID_SIZE))
        p_mean = np.zeros((_GRID_SIZE, _GRID_SIZE))
        for i, y_value in enumerate(ys):
            for j, x_value in enumerate(xs):
                point = replace(
                    reference,
                    id="_grid",
                    name="_grid",
                    **{x_axis: float(x_value), y_axis: float(y_value)},
                )
                mu, sd = self._logit_moments(self._feature_vector(point))
                mean_logits[i, j] = mu
                std_logits[i, j] = sd
                p_mean[i, j] = _sigmoid(mu)

        _, ax = plt.subplots()
        mesh = ax.contourf(xs, ys, p_mean, levels=20, cmap="RdYlGn", vmin=0.0, vmax=1.0)
        plt.colorbar(mesh, ax=ax, label="P(buy)")
        ax.contour(xs, ys, mean_logits, levels=[0.0], colors="black", linewidths=2.0)
        ax.contour(
            xs,
            ys,
            mean_logits - _BOUNDARY_Z * std_logits,
            levels=[0.0],
            colors="black",
            linestyles="--",
            linewidths=1.0,
        )
        ax.contour(
            xs,
            ys,
            mean_logits + _BOUNDARY_Z * std_logits,
            levels=[0.0],
            colors="black",
            linestyles="--",
            linewidths=1.0,
        )
        for item in self._catalog:
            bought = None if labels is None else labels.get(item.id)
            color = _POINT_COLORS.get(bought, "black") if bought is not None else "black"
            ax.scatter(getattr(item, x_axis), getattr(item, y_axis), c=color, s=24, zorder=3)
            ax.annotate(item.id, (getattr(item, x_axis), getattr(item, y_axis)), fontsize=7)
        ax.set_xlabel(x_axis)
        ax.set_ylabel(y_axis)
        ax.set_title(f"{y_axis} vs {x_axis}")
        return ax

    def fit(self, observations: Sequence[tuple[Product, bool]]) -> None:
        labels = [bought for _, bought in observations]
        if not labels or len(set(labels)) < 2:
            self._reset_prior()
            return

        x = torch.stack([self._feature_vector(product) for product, _ in observations])
        y = torch.tensor(labels, dtype=torch.float32)

        pyro.clear_param_store()
        pyro.set_rng_seed(0)
        guide = AutoNormal(logistic_model, init_loc_fn=init_to_mean)
        svi = SVI(logistic_model, guide, Adam({"lr": _SVI_LR}), loss=Trace_ELBO())
        for _ in range(_SVI_STEPS):
            svi.step(x, y, self._prior_scale)

        with torch.no_grad():
            medians = guide.median()
            bias_scale = guide.scales.bias.detach().cpu().reshape(-1)[0]
            weight_scales = guide.scales.weights.detach().cpu().reshape(-1)
        self._bias = float(medians["bias"].reshape(-1)[0])
        self._weights = medians["weights"].detach().cpu().clone().reshape(-1)
        self._bias_scale = float(bias_scale)
        self._weight_scales = weight_scales.clone()
        if self._weights.numel() != len(self._feature_keys):
            self._reset_prior()
