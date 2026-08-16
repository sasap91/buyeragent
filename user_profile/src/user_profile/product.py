from dataclasses import dataclass, asdict
from typing import Any

_ALLOWED_CONDITIONS = frozenset({"NEW", "REFURBISHED", "USED"})


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    brand: str
    price: float
    quality: float
    sustainability: float
    condition: str | None = None
    delivery_days: int | None = None
    return_window_days: int | None = None
    merchant: str | None = None

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("price must be >= 0")
        if not 0.0 <= self.quality <= 1.0:
            raise ValueError("quality must be in [0, 1]")
        if not 0.0 <= self.sustainability <= 1.0:
            raise ValueError("sustainability must be in [0, 1]")
        if self.condition is not None and self.condition not in _ALLOWED_CONDITIONS:
            raise ValueError("condition must be NEW, REFURBISHED, USED, or omitted")
        if self.delivery_days is not None and self.delivery_days < 0:
            raise ValueError("delivery_days must be >= 0")
        if self.return_window_days is not None and self.return_window_days < 0:
            raise ValueError("return_window_days must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Product":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            category=str(data["category"]),
            brand=str(data["brand"]),
            price=float(data["price"]),
            quality=float(data["quality"]),
            sustainability=float(data["sustainability"]),
            condition=data.get("condition"),
            delivery_days=data.get("delivery_days"),
            return_window_days=data.get("return_window_days"),
            merchant=data.get("merchant"),
        )
