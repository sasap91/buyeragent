from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    brand: str
    price: float
    quality: float
    sustainability: float

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("price must be >= 0")
        if not 0.0 <= self.quality <= 1.0:
            raise ValueError("quality must be in [0, 1]")
        if not 0.0 <= self.sustainability <= 1.0:
            raise ValueError("sustainability must be in [0, 1]")
