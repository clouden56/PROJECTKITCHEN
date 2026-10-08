"""
Hardcoded sample Gemini API responses used by the offline test suite.
Each SAMPLE_* constant is a full generateContent response envelope exactly as the
live API returns it, so tests exercise the real parsing path without network access.
Constraints: 100% procedural (NO classes), NO print() statements.
"""

import json
from datetime import date, timedelta


def wrap_in_gemini_envelope(text: str) -> dict:
    """
    Wraps model output text in the generateContent response structure.
    """
    return {
        "candidates": [{
            "content": {"parts": [{"text": text}], "role": "model"},
            "finishReason": "STOP",
            "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 412, "candidatesTokenCount": 238, "totalTokenCount": 650},
        "modelVersion": "gemini-3.6-flash"
    }


def build_sample_inventory(today: date) -> list[dict]:
    """
    Inventory the sample responses were 'generated' against. Expiry dates are relative to
    today so expiry scoring stays deterministic whatever day the suite runs.
    """
    def days_from_today(n: int) -> str:
        return (today + timedelta(days=n)).strftime("%Y-%m-%d")

    return [
        {"id": "ing-001", "name": "Eggs", "quantity": 6, "unit": "pcs", "location": "Fridge", "expiry_date": days_from_today(1)},
        {"id": "ing-002", "name": "Cheddar Cheese", "quantity": 200, "unit": "g", "location": "Fridge", "expiry_date": days_from_today(2)},
        {"id": "ing-003", "name": "Spinach", "quantity": 150, "unit": "g", "location": "Fridge", "expiry_date": days_from_today(0)},
        {"id": "ing-004", "name": "Bread", "quantity": 4, "unit": "slices", "location": "Pantry", "expiry_date": days_from_today(10)},
        {"id": "ing-005", "name": "Chicken Breast", "quantity": 0.5, "unit": "kg", "location": "Fridge", "expiry_date": days_from_today(5)},
        {"id": "ing-006", "name": "Milk", "quantity": 500, "unit": "ml", "location": "Fridge", "expiry_date": days_from_today(3)},
    ]


# Expected outcome: ACCEPTED / OPTIMAL_MATCH (all ingredients owned, quick, uses 3 near-expiry items)
SAMPLE_ACCEPTED = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "Spinach & Cheddar Omelette",
    "meal_type": "Breakfast",
    "estimated_cook_time_mins": 15,
    "required_tools": ["Non-stick Skillet", "Whisk", "Spatula", "Mixing Bowl"],
    "ingredients_used": ["3 Eggs", "50g Cheddar Cheese, shredded", "1 cup fresh Spinach"],
    "missing_ingredients": [],
    "instructions": [
        "Whisk the eggs in a mixing bowl.",
        "Wilt the spinach in the skillet over medium heat for 1 minute.",
        "Pour in the eggs and cook until almost set.",
        "Sprinkle cheddar over half, fold and serve."
    ],
    "waste_reduction_notes": "Uses spinach expiring today plus eggs and cheddar expiring within 2 days."
}))

# Expected outcome: REJECTED / ALLERGEN_CONTAMINATION when user is allergic to dairy
SAMPLE_DAIRY_ALLERGEN = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "Creamy Chicken Alfredo",
    "meal_type": "Dinner",
    "estimated_cook_time_mins": 25,
    "required_tools": ["Large Pot", "Skillet", "Chef Knife"],
    "ingredients_used": ["Chicken Breast", "Milk", "Cheddar Cheese"],
    "missing_ingredients": ["Fettuccine pasta", "Butter"],
    "instructions": ["Boil pasta.", "Sear chicken.", "Simmer milk and cheese into a sauce.", "Combine and serve."],
    "waste_reduction_notes": "Uses milk before it expires."
}))

# Expected outcome: REJECTED / INSUFFICIENT_INGREDIENTS (only 1 of 7 critical ingredients owned)
SAMPLE_INSUFFICIENT = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "Beef Rendang",
    "meal_type": "Dinner",
    "estimated_cook_time_mins": 120,
    "required_tools": ["Dutch Oven", "Mortar and Pestle"],
    "ingredients_used": ["Beef Chuck", "Coconut Cream", "Lemongrass", "Spinach"],
    "missing_ingredients": ["Galangal", "Kaffir Lime Leaves", "Chilli Paste"],
    "instructions": ["Pound the spice paste.", "Brown the beef.", "Simmer in coconut cream for 2 hours."],
    "waste_reduction_notes": "Adds spinach as a side."
}))

# Expected outcome: FLAGGED / EXCEEDS_TIME_LIMIT when the user allows 30 minutes
SAMPLE_OVER_TIME = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "Baked Chicken Breast with Spinach",
    "meal_type": "Dinner",
    "estimated_cook_time_mins": 50,
    "required_tools": ["Oven", "Baking Tray"],
    "ingredients_used": ["Chicken Breast", "Spinach"],
    "missing_ingredients": [],
    "instructions": ["Preheat oven to 200C.", "Bake chicken for 40 minutes.", "Serve on wilted spinach."],
    "waste_reduction_notes": "Rescues spinach expiring today."
}))

# Expected outcome: FLAGGED / MISSING_SOME_INGREDIENTS (3 of 5 owned = 60% >= 50% threshold)
SAMPLE_MISSING_SOME = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "French Toast",
    "meal_type": "Breakfast",
    "estimated_cook_time_mins": 15,
    "required_tools": ["Skillet", "Shallow Dish", "Spatula"],
    "ingredients_used": ["Bread", "Eggs", "Milk"],
    "missing_ingredients": ["Maple Syrup", "Cinnamon"],
    "instructions": ["Whisk eggs and milk.", "Soak bread slices.", "Fry until golden."],
    "waste_reduction_notes": "Uses milk and eggs close to expiry."
}))

# Valid recipe wrapped in a markdown code fence (seen from some fallback models); must still parse
SAMPLE_FENCED_JSON = wrap_in_gemini_envelope(
    "```json\n" + json.dumps({
        "recipe_name": "Cheese Toast",
        "meal_type": "Snack",
        "estimated_cook_time_mins": 5,
        "required_tools": ["Toaster Oven"],
        "ingredients_used": ["Bread", "Cheddar Cheese"],
        "missing_ingredients": [],
        "instructions": ["Top bread with cheese.", "Toast until melted."],
        "waste_reduction_notes": "Uses cheddar before it expires."
    }) + "\n```"
)

# --- Malformed responses: every one must be rejected without raising an exception ---

MALFORMED_PROSE_NOT_JSON = wrap_in_gemini_envelope(
    "Sure! Here is a lovely omelette recipe: whisk 3 eggs, add spinach and cheese, then fry."
)

MALFORMED_MISSING_FIELD = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "Mystery Stew",
    "meal_type": "Dinner",
    "estimated_cook_time_mins": 30,
    "required_tools": ["Pot"],
    "ingredients_used": ["Chicken Breast"],
    "missing_ingredients": [],
    "waste_reduction_notes": "n/a"
}))

MALFORMED_WRONG_TYPE = wrap_in_gemini_envelope(json.dumps({
    "recipe_name": "Quick Eggs",
    "meal_type": "Breakfast",
    "estimated_cook_time_mins": "about 10 minutes",
    "required_tools": ["Pan"],
    "ingredients_used": ["Eggs"],
    "missing_ingredients": [],
    "instructions": ["Scramble the eggs."],
    "waste_reduction_notes": "Uses eggs."
}))

MALFORMED_TOP_LEVEL_ARRAY = wrap_in_gemini_envelope(json.dumps(["Eggs", "Spinach", "Cheese"]))

MALFORMED_EMPTY_TEXT = wrap_in_gemini_envelope("")

MALFORMED_TRUNCATED_JSON = wrap_in_gemini_envelope('{"recipe_name": "Spinach Omelette", "meal_type": "Break')

MALFORMED_SAFETY_BLOCKED = {"promptFeedback": {"blockReason": "SAFETY"}}

MALFORMED_NO_PARTS = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}

MALFORMED_UNEXPECTED_SHAPE = {"candidates": ["unexpected string instead of an object"]}

ALL_MALFORMED_RESPONSES = {
    "prose instead of JSON": MALFORMED_PROSE_NOT_JSON,
    "missing 'instructions' field": MALFORMED_MISSING_FIELD,
    "string cook time": MALFORMED_WRONG_TYPE,
    "top-level JSON array": MALFORMED_TOP_LEVEL_ARRAY,
    "empty text": MALFORMED_EMPTY_TEXT,
    "truncated JSON": MALFORMED_TRUNCATED_JSON,
    "safety-blocked (no candidates)": MALFORMED_SAFETY_BLOCKED,
    "candidate with no parts": MALFORMED_NO_PARTS,
    "candidate is not an object": MALFORMED_UNEXPECTED_SHAPE,
}
