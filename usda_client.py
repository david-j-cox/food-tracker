"""USDA FoodData Central API client for food search and nutrient lookup."""

import requests

from config import Config

BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# USDA nutrient ID -> our column name mapping
NUTRIENT_MAP = {
    1008: "calories",           # Energy (kcal)
    1003: "protein_g",          # Protein
    1004: "total_fat_g",        # Total lipid (fat)
    1258: "saturated_fat_g",    # Fatty acids, total saturated
    1005: "carbohydrates_g",    # Carbohydrate, by difference
    1079: "fiber_g",            # Fiber, total dietary
    2000: "sugar_g",            # Sugars, total including NLEA
    1093: "sodium_mg",          # Sodium, Na
    1089: "iron_mg",            # Iron, Fe
    1087: "calcium_mg",         # Calcium, Ca
    1090: "magnesium_mg",       # Magnesium, Mg
    1092: "potassium_mg",       # Potassium, K
    1178: "vitamin_b12_mcg",    # Vitamin B-12
    1114: "vitamin_d_mcg",      # Vitamin D (D2 + D3)
}


def search_foods(query: str, limit: int = 5) -> list[dict]:
    """Search USDA FoodData Central for foods matching the query.

    Returns list of dicts with keys: fdc_id, description, brand, data_type
    """
    resp = requests.get(
        f"{BASE_URL}/foods/search",
        params={
            "api_key": Config.USDA_API_KEY,
            "query": query,
            "pageSize": limit,
            "dataType": "Foundation,SR Legacy,Branded",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for food in data.get("foods", []):
        results.append({
            "fdc_id": food["fdcId"],
            "description": food.get("description", ""),
            "brand": food.get("brandOwner") or food.get("brandName") or None,
            "data_type": food.get("dataType", ""),
        })
    return results


def get_food_nutrients(fdc_id: int) -> dict:
    """Fetch full nutrient profile for a specific food item.

    Returns dict with our standard nutrient column names as keys.
    """
    resp = requests.get(
        f"{BASE_URL}/food/{fdc_id}",
        params={"api_key": Config.USDA_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    nutrients = {col: None for col in NUTRIENT_MAP.values()}

    for nutrient in data.get("foodNutrients", []):
        # Handle both search result format and detail format
        if "nutrient" in nutrient:
            nid = nutrient["nutrient"].get("id")
            amount = nutrient.get("amount")
        else:
            nid = nutrient.get("nutrientId")
            amount = nutrient.get("value") or nutrient.get("amount")

        if nid in NUTRIENT_MAP and amount is not None:
            nutrients[NUTRIENT_MAP[nid]] = round(float(amount), 2)

    return nutrients
