from collections.abc import Sequence
from itertools import combinations, product as cartesian_product
from math import exp, sqrt

import pyro
import pyro.distributions as dist
import torch
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
        self._bias = 0.0
        self._weights = torch.zeros(len(self._feature_keys), dtype=torch.float32)

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
        self._bias = float(medians["bias"].reshape(-1)[0])
        self._weights = medians["weights"].detach().cpu().clone().reshape(-1)
        if self._weights.numel() != len(self._feature_keys):
            self._weights = torch.zeros(len(self._feature_keys), dtype=torch.float32)
