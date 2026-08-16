from user_profile.preferences import User, UserPreferences
from user_profile.product import Product

PRODUCTS: tuple[Product, ...] = (
    Product(
        id="budget_headphones",
        name="Studio Lite Headphones",
        category="headphones",
        brand="Generic",
        price=25.0,
        quality=0.35,
        sustainability=0.20,
    ),
    Product(
        id="sony_xm5",
        name="Sony WH-1000XM5",
        category="headphones",
        brand="Sony",
        price=350.0,
        quality=0.95,
        sustainability=0.50,
    ),
    Product(
        id="overpriced_clone",
        name="Studio Lite Pro Headphones",
        category="headphones",
        brand="Generic",
        price=80.0,
        quality=0.30,
        sustainability=0.15,
    ),
    Product(
        id="basic_bottle",
        name="Plain Steel Bottle",
        category="bottle",
        brand="Generic",
        price=8.0,
        quality=0.40,
        sustainability=0.30,
    ),
    Product(
        id="hydro_flask",
        name="Hydro Flask Standard Mouth",
        category="bottle",
        brand="HydroFlask",
        price=45.0,
        quality=0.85,
        sustainability=0.70,
    ),
    Product(
        id="eco_bottle",
        name="Rebottle Plant-Based Bottle",
        category="bottle",
        brand="EcoWare",
        price=15.0,
        quality=0.50,
        sustainability=0.95,
    ),
    Product(
        id="luxury_bottle",
        name="Hydro Flask Limited Edition",
        category="bottle",
        brand="HydroFlask",
        price=90.0,
        quality=0.80,
        sustainability=0.60,
    ),
    Product(
        id="budget_runners",
        name="Fleet Road Shoes",
        category="sneakers",
        brand="Generic",
        price=40.0,
        quality=0.45,
        sustainability=0.25,
    ),
    Product(
        id="nike_pegasus",
        name="Nike Pegasus 41",
        category="sneakers",
        brand="Nike",
        price=130.0,
        quality=0.85,
        sustainability=0.40,
    ),
    Product(
        id="allbirds",
        name="Allbirds Tree Runner",
        category="sneakers",
        brand="Allbirds",
        price=110.0,
        quality=0.75,
        sustainability=0.90,
    ),
    Product(
        id="mr_coffee",
        name="Mr. Coffee 12-Cup",
        category="coffee",
        brand="MrCoffee",
        price=30.0,
        quality=0.50,
        sustainability=0.30,
    ),
    Product(
        id="fellow_kettle",
        name="Fellow Stagg EKG",
        category="coffee",
        brand="Fellow",
        price=165.0,
        quality=0.80,
        sustainability=0.65,
    ),
)

MAYA = User(
    id="maya",
    name="Maya",
    preferences=UserPreferences(
        price_weight=0.55,
        quality_weight=0.25,
        brand_weight=0.10,
        sustainability_weight=0.10,
        brand_affinities={"Generic": 0.40, "MrCoffee": 0.50, "EcoWare": 0.30},
        max_price=150.0,
    ),
)

JORDAN = User(
    id="jordan",
    name="Jordan",
    preferences=UserPreferences(
        price_weight=0.10,
        quality_weight=0.40,
        brand_weight=0.40,
        sustainability_weight=0.10,
        brand_affinities={
            "Sony": 0.95,
            "Nike": 0.90,
            "HydroFlask": 0.70,
            "Fellow": 0.60,
        },
        min_quality=0.70,
    ),
)

RILEY = User(
    id="riley",
    name="Riley",
    preferences=UserPreferences(
        price_weight=0.15,
        quality_weight=0.20,
        brand_weight=0.15,
        sustainability_weight=0.50,
        brand_affinities={
            "Allbirds": 0.80,
            "EcoWare": 0.90,
            "HydroFlask": 0.70,
            "Fellow": 0.50,
        },
    ),
)

USERS: tuple[User, ...] = (MAYA, JORDAN, RILEY)
