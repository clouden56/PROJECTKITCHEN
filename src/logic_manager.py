"""
Logic Manager Module
Responsibility: Domain brain, business rules, allergen verification, expiry scoring, and multi-condition outcome routing.
Architecture Layer: Logic Layer
Framework functions: evaluate(record), score(record), route(evaluation).
Constraints: 100% procedural (no classes), no terminal I/O.
"""

from datetime import datetime, date

# Allergen synonym dictionary for enhanced safety checks
ALLERGEN_MAP = {
    "dairy": ["milk", "cheese", "butter", "cream", "yogurt", "ghee"],
    "nuts": ["peanut", "almond", "walnut", "cashew", "pistachio", "pecan", "hazelnut"],
    "gluten": ["flour", "bread", "pasta", "wheat", "barley", "rye"],
    "egg": ["egg", "eggs", "mayonnaise"],
    "shellfish": ["shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster"],
    "soy": ["soy", "soya", "tofu", "edamame", "soy sauce"]
}


def calculate_days_until_expiry(expiry_date_str: str, reference_date: date | None = None) -> int:
    """
    Calculates number of days remaining until expiry from the reference date (defaults to today).
    Positive = unexpired; 0 = expires today; Negative = expired.
    """
    if reference_date is None:
        reference_date = datetime.now().date()

    try:
        exp_date = datetime.strptime(expiry_date_str.strip(), "%Y-%m-%d").date()
        return (exp_date - reference_date).days
    except (ValueError, TypeError, AttributeError):
        return 999  # Treat missing or malformed date as non-urgent


def evaluate_allergen_safety(recipe: dict, user_allergies: list[str]) -> tuple[bool, list[str]]:
    """
    Checks all ingredients in the recipe against user specified allergies.
    Supports plural/singular stemming and allergen synonym mapping.
    Returns (is_safe: bool, detected_allergens: list[str]).
    """
    if not user_allergies:
        return True, []

    normalized_allergies = [a.strip().lower() for a in user_allergies if a.strip()]
    if not normalized_allergies:
        return True, []

    # Gather all recipe ingredients
    all_recipe_ingredients = [
        str(i).lower() for i in recipe.get("ingredients_used", []) + recipe.get("missing_ingredients", [])
    ]

    detected = []
    for allergen in normalized_allergies:
        allergen_stem = allergen[:-1] if allergen.endswith("s") and len(allergen) > 3 else allergen

        for ing in all_recipe_ingredients:
            # Direct or stemmed match
            if allergen in ing or allergen_stem in ing:
                detected.append(f"{allergen} found in '{ing}'")
                continue

            # Check allergen synonyms
            synonyms = ALLERGEN_MAP.get(allergen, []) or ALLERGEN_MAP.get(allergen_stem, [])
            for syn in synonyms:
                syn_stem = syn[:-1] if syn.endswith("s") and len(syn) > 3 else syn
                if syn in ing or syn_stem in ing:
                    detected.append(f"{allergen} ({syn}) found in '{ing}'")
                    break

    unique_detected = list(dict.fromkeys(detected))
    is_safe = len(unique_detected) == 0
    return is_safe, unique_detected


def find_used_inventory_items(recipe: dict, inventory: list[dict]) -> list[dict]:
    """
    Returns the inventory items the AI recipe uses, each with its days until expiry.
    """
    used_names = [str(name).strip().lower() for name in recipe.get("ingredients_used", [])]
    used_items = []
    for inv_item in inventory:
        inv_name = inv_item.get("name", "").strip().lower()
        if inv_name and any(inv_name in u or u in inv_name for u in used_names):
            used_items.append({
                "name": inv_item.get("name"),
                "days_until_expiry": calculate_days_until_expiry(inv_item.get("expiry_date", "")),
                "quantity": inv_item.get("quantity"),
                "unit": inv_item.get("unit")
            })
    return used_items


def expiry_points(days_until_expiry: int) -> int:
    """
    Urgency weight of one used ingredient: expired/today 40, 1-3 days 30, 4-7 days 15, otherwise 5.
    """
    if days_until_expiry <= 0:
        return 40
    if days_until_expiry <= 3:
        return 30
    if days_until_expiry <= 7:
        return 15
    return 5


def score(record: dict) -> float:
    """
    Expiry-priority score (0-100) of an AI-enriched record: how strongly the AI's recipe
    (record["recipe"]["ingredients_used"]) consumes inventory that is close to expiry.
    Used to rank recipes by food-waste impact.
    """
    used_items = find_used_inventory_items(record.get("recipe", {}), record.get("inventory", []))
    return min(100.0, float(sum(expiry_points(i["days_until_expiry"]) for i in used_items)))


def find_rescued_items(recipe: dict, inventory: list[dict]) -> list[dict]:
    """
    Used inventory items expiring within 7 days (the ones this recipe rescues from waste).
    """
    return [i for i in find_used_inventory_items(recipe, inventory) if i["days_until_expiry"] <= 7]


COMMON_PANTRY_STAPLES = {"salt", "pepper", "black pepper", "water", "cooking oil", "oil", "butter"}


def normalize_ingredient_words(text: str) -> set[str]:
    """
    Strips quantities, units, and returns a set of normalized, stemmed words.
    """
    stopwords = {"tsp", "tbsp", "cup", "cups", "g", "ml", "pcs", "pinch", "pinches", "of", "fresh", "diced", "shredded", "sliced", "a", "an", "the", "or"}
    words = text.lower().replace("-", " ").replace(",", " ").split()
    stems = set()
    for w in words:
        # Strip digits
        w = "".join([c for c in w if c.isalpha()])
        if not w or w in stopwords:
            continue
        # Simple stemming for plurals
        if w.endswith("es") and len(w) > 4:
            stems.add(w[:-2])
        elif w.endswith("s") and len(w) > 3:
            stems.add(w[:-1])
        stems.add(w)
    return stems


def does_ingredient_match(ing1: str, ing2: str) -> bool:
    """
    Checks whether two ingredient descriptions refer to the same ingredient
    using substring matching and stemmed keyword intersections.
    """
    s1 = ing1.strip().lower()
    s2 = ing2.strip().lower()

    if s1 in s2 or s2 in s1:
        return True

    words1 = normalize_ingredient_words(s1)
    words2 = normalize_ingredient_words(s2)

    return bool(words1.intersection(words2))


def calculate_ingredient_match_ratio(recipe: dict, inventory: list[dict]) -> tuple[float, list[str], list[str]]:
    """
    Calculates the proportion of recipe ingredients that the user currently possesses in inventory.
    Filters out optional pantry seasonings from penalizing match ratio.
    Returns (ratio: float, matched_ingredients: list[str], missing_ingredients: list[str]).
    """
    recipe_used = recipe.get("ingredients_used", [])
    recipe_missing = recipe.get("missing_ingredients", [])

    inv_names = [item.get("name", "").strip() for item in inventory]

    matched = []
    missing = []

    for item_name in recipe_used:
        if any(does_ingredient_match(item_name, inv) for inv in inv_names):
            matched.append(item_name)
        else:
            missing.append(item_name)

    # Process explicit missing ingredients from AI
    staple_words = set()
    for staple in COMMON_PANTRY_STAPLES:
        staple_words |= normalize_ingredient_words(staple)

    critical_missing = []
    for m in recipe_missing:
        m_words = normalize_ingredient_words(m)
        # Items made only of staple words (salt, black pepper, cooking oil) don't count against the ratio
        if m_words and m_words <= staple_words:
            continue
        critical_missing.append(m)

    all_critical_missing = missing + critical_missing
    total_critical = len(matched) + len(all_critical_missing)

    if total_critical == 0:
        ratio = 1.0 if matched else 0.0
    else:
        ratio = round(len(matched) / float(total_critical), 2)

    all_missing_reported = list(dict.fromkeys(missing + recipe_missing))
    return ratio, matched, all_missing_reported


def estimate_food_waste_diverted(rescued_items: list[dict]) -> int:
    """
    Estimates the grams of potential food waste diverted from landfills.
    Standard heuristic: ~120 grams per rescued perishable item.
    """
    total_grams = 0
    for item in rescued_items:
        days = item.get("days_until_expiry", 999)
        if days <= 3:
            # Perishable unit estimate
            qty = item.get("quantity", 1)
            try:
                qty_val = float(qty)
            except (ValueError, TypeError):
                qty_val = 1.0

            unit = str(item.get("unit", "")).lower()
            if unit in ["g", "grams"]:
                total_grams += int(qty_val)
            elif unit in ["kg", "kilograms"]:
                total_grams += int(qty_val * 1000)
            elif unit in ["ml", "milliliters"]:
                total_grams += int(qty_val)  # approx 1g/ml
            else:
                total_grams += int(qty_val * 100)  # default estimate ~100g per unit

    return total_grams


def check_mandatory_ingredients(recipe: dict, mandatory_ingredients: list[str]) -> tuple[bool, list[str]]:
    """
    Verifies if all mandatory ingredients specified by the user are included
    in the recipe's ingredients_used.
    Returns: (all_met: bool, missing_mandatory: list[str])
    """
    if not mandatory_ingredients:
        return True, []

    recipe_used = recipe.get("ingredients_used", [])
    missing = []

    for req in mandatory_ingredients:
        req_clean = req.strip()
        if not req_clean:
            continue
        if not any(does_ingredient_match(req_clean, used) for used in recipe_used):
            missing.append(req_clean)

    return len(missing) == 0, missing


def route(evaluation: dict) -> dict:
    """
    Assigns an evaluated record to an outcome path. Multi-condition rule over AI response fields
    (ingredients_used, missing_ingredients, estimated_cook_time_mins) and the user's constraints;
    checked in order, first match wins.
    Returns {"outcome": ACCEPTED|FLAGGED|REJECTED, "status_code": str, "status_message": str}.
    """
    ratio_pct = int(evaluation["match_ratio"] * 100)
    min_pct = int(evaluation["min_match_ratio"] * 100)

    if not evaluation["allergen_safe"]:
        return {
            "outcome": "REJECTED",
            "status_code": "ALLERGEN_CONTAMINATION",
            "status_message": f"Recipe rejected due to detected allergens: {', '.join(evaluation['allergen_violations'])}."
        }
    if evaluation["match_ratio"] < evaluation["min_match_ratio"]:
        return {
            "outcome": "REJECTED",
            "status_code": "INSUFFICIENT_INGREDIENTS",
            "status_message": f"Ingredient match ratio ({ratio_pct}%) is below the minimum threshold of {min_pct}%."
        }
    if not evaluation["mandatory_met"]:
        return {
            "outcome": "FLAGGED",
            "status_code": "MISSING_MANDATORY_INGREDIENT",
            "status_message": (
                "Recipe generated but missing your requested mandatory ingredient(s): "
                f"{', '.join(evaluation['missing_mandatory'])}."
            )
        }
    if not evaluation["is_within_time"]:
        return {
            "outcome": "FLAGGED",
            "status_code": "EXCEEDS_TIME_LIMIT",
            "status_message": (
                f"Recipe cook time ({evaluation['cook_time_mins']} mins) exceeds your limit of "
                f"{evaluation['max_cook_time_mins']} mins, but has a good ingredient match ({ratio_pct}%)."
            )
        }
    if evaluation["missing_ingredients"]:
        return {
            "outcome": "FLAGGED",
            "status_code": "MISSING_SOME_INGREDIENTS",
            "status_message": (
                f"Recipe approved with caution ({ratio_pct}% match). "
                f"Missing items: {', '.join(evaluation['missing_ingredients'])}."
            )
        }
    return {
        "outcome": "ACCEPTED",
        "status_code": "OPTIMAL_MATCH",
        "status_message": "Recipe perfectly matches your fridge ingredients and cooking parameters!"
    }


def evaluate(record: dict, min_match_ratio: float = 0.50) -> dict:
    """
    Runs every business rule against an AI-enriched record and returns the decision dict.
    record keys: recipe (validated AI output), inventory, max_cook_time_mins, allergies,
                 mandatory_ingredients (optional)
    """
    recipe = record.get("recipe", {})
    inventory = record.get("inventory", [])
    max_cook_time_mins = record.get("max_cook_time_mins", 0)

    is_safe, allergen_violations = evaluate_allergen_safety(recipe, record.get("allergies", []))
    match_ratio, matched_ings, missing_ings = calculate_ingredient_match_ratio(recipe, inventory)
    mandatory_met, missing_mandatory = check_mandatory_ingredients(recipe, record.get("mandatory_ingredients") or [])
    rescued_items = find_rescued_items(recipe, inventory)
    cook_time = recipe.get("estimated_cook_time_mins", 0)

    evaluation = {
        "allergen_safe": is_safe,
        "allergen_violations": allergen_violations,
        "match_ratio": match_ratio,
        "min_match_ratio": min_match_ratio,
        "match_percentage": int(match_ratio * 100),
        "matched_ingredients": matched_ings,
        "missing_ingredients": missing_ings,
        "mandatory_met": mandatory_met,
        "missing_mandatory": missing_mandatory,
        "cook_time_mins": cook_time,
        "max_cook_time_mins": max_cook_time_mins,
        "is_within_time": cook_time <= max_cook_time_mins,
        "expiry_priority_score": score(record),
        "rescued_items": rescued_items,
        "waste_diverted_grams": estimate_food_waste_diverted(rescued_items),
    }
    evaluation.update(route(evaluation))
    return evaluation
