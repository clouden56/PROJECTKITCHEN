"""
Logic Manager Module
Responsibility: Domain brain, business rules, allergen verification, expiry scoring, and multi-condition outcome routing.
Architecture Layer: Logic Layer
Constraints: 100% procedural (NO classes), NO print() statements.
"""

from datetime import datetime, date
from typing import Any

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


def calculate_expiry_priority_score(recipe: dict, inventory: list[dict]) -> tuple[float, list[dict]]:
    """
    Computes a score (0 to 100) reflecting how effectively the recipe
    consumes ingredients close to expiration (<= 3 days).
    Returns (score, list_of_rescued_inventory_items).
    """
    used_names = [str(name).strip().lower() for name in recipe.get("ingredients_used", [])]
    rescued_items = []
    raw_points = 0

    for inv_item in inventory:
        inv_name = inv_item.get("name", "").strip().lower()
        if any(inv_name in u or u in inv_name for u in used_names):
            days = calculate_days_until_expiry(inv_item.get("expiry_date", ""))
            item_record = {
                "name": inv_item.get("name"),
                "days_until_expiry": days,
                "quantity": inv_item.get("quantity"),
                "unit": inv_item.get("unit")
            }

            if days <= 0:
                # Expired or expires today
                raw_points += 40
                rescued_items.append(item_record)
            elif days <= 3:
                # Critical rescue (1-3 days remaining)
                raw_points += 30
                rescued_items.append(item_record)
            elif days <= 7:
                # Moderate urgency (4-7 days remaining)
                raw_points += 15
                rescued_items.append(item_record)
            else:
                raw_points += 5

    # Cap score at 100
    normalized_score = min(100.0, float(raw_points))
    return normalized_score, rescued_items


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
    critical_missing = []
    for m in recipe_missing:
        m_words = normalize_ingredient_words(m)
        # If it's just a common seasoning staple (salt, pepper, water), classify softly
        if any(staple in m.lower() for staple in COMMON_PANTRY_STAPLES) and not (m_words - {"salt", "pepper", "oil", "water", "butter"}):
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


def evaluate_recipe(
    recipe: dict,
    inventory: list[dict],
    max_cook_time_mins: int,
    user_allergies: list[str],
    min_match_ratio: float = 0.50
) -> dict:
    """
    Core Domain Rule: Multi-condition evaluation pipeline acting on AI output.
    Applies business logic combining allergen safety, time constraints, match threshold,
    and expiry score to route into an outcome: ACCEPTED, FLAGGED, or REJECTED.
    """
    # 1. Evaluate Allergen Safety
    is_safe, allergen_violations = evaluate_allergen_safety(recipe, user_allergies)

    # 2. Match Ratio Calculation
    match_ratio, matched_ings, missing_ings = calculate_ingredient_match_ratio(recipe, inventory)

    # 3. Expiry Priority Score & Rescued Items
    expiry_score, rescued_items = calculate_expiry_priority_score(recipe, inventory)

    # 4. Cook Time Constraint Check
    cook_time = recipe.get("estimated_cook_time_mins", 0)
    is_within_time = cook_time <= max_cook_time_mins

    # 5. Waste Impact
    waste_diverted_grams = estimate_food_waste_diverted(rescued_items)

    # --- Multi-Condition Decision Routing ---
    if not is_safe:
        outcome = "REJECTED"
        status_code = "ALLERGEN_CONTAMINATION"
        status_message = f"Recipe rejected due to detected allergens: {', '.join(allergen_violations)}."
    elif match_ratio < min_match_ratio:
        outcome = "REJECTED"
        status_code = "INSUFFICIENT_INGREDIENTS"
        status_message = (
            f"Ingredient match ratio ({int(match_ratio * 100)}%) is below the "
            f"minimum threshold of {int(min_match_ratio * 100)}%."
        )
    elif not is_within_time and match_ratio >= min_match_ratio:
        outcome = "FLAGGED"
        status_code = "EXCEEDS_TIME_LIMIT"
        status_message = (
            f"Recipe cook time ({cook_time} mins) exceeds your limit of {max_cook_time_mins} mins, "
            f"but has a good ingredient match ({int(match_ratio * 100)}%)."
        )
    elif missing_ings and match_ratio >= min_match_ratio:
        outcome = "FLAGGED"
        status_code = "MISSING_SOME_INGREDIENTS"
        status_message = (
            f"Recipe approved with caution ({int(match_ratio * 100)}% match). "
            f"Missing items: {', '.join(missing_ings)}."
        )
    else:
        outcome = "ACCEPTED"
        status_code = "OPTIMAL_MATCH"
        status_message = "Recipe perfectly matches your fridge ingredients and cooking parameters!"

    evaluation_record = {
        "outcome": outcome,
        "status_code": status_code,
        "status_message": status_message,
        "match_ratio": match_ratio,
        "match_percentage": int(match_ratio * 100),
        "matched_ingredients": matched_ings,
        "missing_ingredients": missing_ings,
        "expiry_priority_score": expiry_score,
        "rescued_items": rescued_items,
        "waste_diverted_grams": waste_diverted_grams,
        "is_within_time": is_within_time,
        "allergen_safe": is_safe
    }

    return evaluation_record
