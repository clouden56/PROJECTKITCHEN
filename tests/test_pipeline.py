"""
Automated Verification Suite
Constraints: 100% procedural (NO classes anywhere, even in tests!), NO print() in core logic.
"""

import os
import sys
import json
import re
import tempfile
from datetime import datetime, timedelta

# Ensure src is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import data_manager
from src import ai_manager
from src import logic_manager


def test_zero_classes_in_codebase() -> bool:
    """
    Scans all Python files in the repository to guarantee 100% procedural compliance.
    Fails if a single 'class ' definition is found.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    class_pattern = re.compile(r"^\s*class\s+[A-Za-z_][A-Za-z0-9_]*(\(.*\))?:", re.MULTILINE)

    violations = []
    for root, dirs, files in os.walk(root_dir):
        # Exclude hidden, venv, git directories
        if any(part.startswith(".") or part in ["venv", "env", "__pycache__"] for part in root.split(os.sep)):
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    matches = class_pattern.findall(content)
                    if matches:
                        violations.append((path, len(matches)))

    if violations:
        raise AssertionError(f"Class definitions detected in codebase: {violations}")
    return True


def test_no_prints_outside_io_manager() -> bool:
    """
    Guarantees that all print() calls in the system live in src/io_manager.py and nowhere else.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print_pattern = re.compile(r"^\s*print\(", re.MULTILINE)

    violations = []
    for root, dirs, files in os.walk(root_dir):
        if any(part.startswith(".") or part in ["venv", "env", "__pycache__"] for part in root.split(os.sep)):
            continue
        for file in files:
            if file.endswith(".py"):
                rel_path = os.path.relpath(os.path.join(root, file), root_dir).replace("\\", "/")
                # Allowed only in src/io_manager.py or test output reporter
                if rel_path in ["src/io_manager.py", "tests/test_pipeline.py"]:
                    continue
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    matches = print_pattern.findall(content)
                    if matches:
                        violations.append((rel_path, len(matches)))

    if violations:
        raise AssertionError(f"Illegal print() calls found outside io_manager: {violations}")
    return True


def test_data_manager_operations() -> bool:
    """
    Tests saving, loading, updating, removing, and corrupt file recovery.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        inv_file = os.path.join(tmp_dir, "test_inv.json")
        rec_file = os.path.join(tmp_dir, "test_rec.json")

        # 1. Non-existent file returns default empty list
        inv = data_manager.load_inventory(inv_file)
        assert inv == [], "Expected empty inventory on non-existent file"

        # 2. Add items
        item1 = {
            "name": "Milk",
            "quantity": 1,
            "unit": "liter",
            "location": "Fridge",
            "expiry_date": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        }
        item2 = {
            "name": "Apples",
            "quantity": 4,
            "unit": "pcs",
            "location": "Fridge",
            "expiry_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        }
        inv = data_manager.add_inventory_item(inv, item1)
        inv = data_manager.add_inventory_item(inv, item2)
        assert len(inv) == 2, "Expected 2 items in inventory"
        data_manager.save_inventory(inv, inv_file)

        # 3. Reload from disk
        reloaded = data_manager.load_inventory(inv_file)
        assert len(reloaded) == 2
        assert reloaded[0]["name"] == "Milk"

        # 4. Query expiring soon (within 3 days)
        expiring = data_manager.query_items_by_expiry(reloaded, max_days=3)
        assert len(expiring) == 1
        assert expiring[0]["name"] == "Milk"

        # 5. Remove item
        updated_inv, was_removed = data_manager.remove_inventory_item(reloaded, "Milk")
        assert was_removed is True
        assert len(updated_inv) == 1
        assert updated_inv[0]["name"] == "Apples"

        # 6. Save recipe history and query
        recipe_entry = {
            "recipe": {
                "recipe_name": "Apple Tart",
                "meal_type": "Snack",
                "ingredients_used": ["Apples", "Flour"]
            },
            "evaluation": {"outcome": "ACCEPTED"}
        }
        data_manager.save_recipe_to_history(recipe_entry, rec_file)
        hist = data_manager.load_recipe_history(rec_file)
        assert len(hist) == 1

        snack_recipes = data_manager.filter_recipes_by_meal_type(hist, "Snack")
        assert len(snack_recipes) == 1
        dinner_recipes = data_manager.filter_recipes_by_meal_type(hist, "Dinner")
        assert len(dinner_recipes) == 0

        apple_matches = data_manager.search_recipes_by_ingredient(hist, "Apple")
        assert len(apple_matches) == 1

        # 7. Corrupt file resilience
        with open(inv_file, "w", encoding="utf-8") as f:
            f.write("MALFORMED_JSON{{{[[[")
        recovered = data_manager.load_inventory(inv_file)
        assert recovered == [], "Expected empty fallback when JSON file is corrupted"

    return True


def test_ai_manager_schema_validation() -> bool:
    """
    Tests JSON schema validation for valid and malformed AI outputs.
    """
    valid_payload = {
        "recipe_name": "Cheese Omelette",
        "meal_type": "Breakfast",
        "estimated_cook_time_mins": 10,
        "required_tools": ["Non-stick skillet", "Spatula", "Mixing bowl"],
        "ingredients_used": ["Eggs", "Cheddar Cheese"],
        "missing_ingredients": ["Black Pepper"],
        "instructions": [
            "Beat eggs in a bowl.",
            "Pour into pan and cook on medium heat.",
            "Fold in cheddar cheese and serve."
        ],
        "waste_reduction_notes": "Uses expiring eggs and leftover cheese."
    }

    is_valid, cleaned, err = ai_manager.validate_recipe_schema(valid_payload)
    assert is_valid is True, f"Valid payload rejected: {err}"
    assert cleaned["recipe_name"] == "Cheese Omelette"
    assert len(cleaned["instructions"]) == 3
    assert len(cleaned["required_tools"]) == 3
    assert "Spatula" in cleaned["required_tools"]

    # Malformed cases
    missing_key = dict(valid_payload)
    del missing_key["instructions"]
    is_valid_bad, _, _ = ai_manager.validate_recipe_schema(missing_key)
    assert is_valid_bad is False, "Expected rejection for missing required field"

    missing_tools = dict(valid_payload)
    del missing_tools["required_tools"]
    is_valid_tools_bad, _, _ = ai_manager.validate_recipe_schema(missing_tools)
    assert is_valid_tools_bad is False, "Expected rejection for missing required_tools"

    wrong_type = dict(valid_payload)
    wrong_type["estimated_cook_time_mins"] = "ten minutes"
    is_valid_type, _, _ = ai_manager.validate_recipe_schema(wrong_type)
    assert is_valid_type is False, "Expected rejection for string cook time"

    empty_ings = dict(valid_payload)
    empty_ings["ingredients_used"] = []
    is_valid_empty, _, _ = ai_manager.validate_recipe_schema(empty_ings)
    assert is_valid_empty is False, "Expected rejection for empty ingredients_used"

    return True


def test_logic_manager_rules() -> bool:
    """
    Tests allergen filtering, expiry prioritization, mandatory ingredient checks,
    and multi-condition evaluation outcomes.
    """
    today = datetime.now().date()
    inventory = [
        {
            "name": "Eggs",
            "quantity": 4,
            "unit": "pcs",
            "expiry_date": (today + timedelta(days=1)).strftime("%Y-%m-%d")
        },
        {
            "name": "Cheddar Cheese",
            "quantity": 100,
            "unit": "g",
            "expiry_date": (today + timedelta(days=2)).strftime("%Y-%m-%d")
        },
        {
            "name": "Bread",
            "quantity": 2,
            "unit": "slices",
            "expiry_date": (today + timedelta(days=10)).strftime("%Y-%m-%d")
        }
    ]

    # 1. Allergen safety test
    safe_recipe = {
        "recipe_name": "Egg Toast",
        "ingredients_used": ["Eggs", "Bread"],
        "missing_ingredients": []
    }
    is_safe, violations = logic_manager.evaluate_allergen_safety(safe_recipe, ["peanuts", "shellfish"])
    assert is_safe is True
    assert len(violations) == 0

    unsafe_recipe = {
        "recipe_name": "Peanut Toast",
        "ingredients_used": ["Bread", "Peanut butter"],
        "missing_ingredients": []
    }
    is_safe2, violations2 = logic_manager.evaluate_allergen_safety(unsafe_recipe, ["peanuts"])
    assert is_safe2 is False
    assert len(violations2) > 0

    # 2. Expiry priority score
    score, rescued = logic_manager.calculate_expiry_priority_score(safe_recipe, inventory)
    assert score > 0, "Score should reflect rescue of expiring Eggs"
    assert any(r["name"] == "Eggs" for r in rescued)

    # 3. Multi-condition rule: ACCEPTED outcome
    eval_accepted = logic_manager.evaluate_recipe(
        recipe={
            "recipe_name": "Scrambled Eggs on Toast",
            "estimated_cook_time_mins": 10,
            "ingredients_used": ["Eggs", "Bread"],
            "missing_ingredients": []
        },
        inventory=inventory,
        max_cook_time_mins=15,
        user_allergies=[],
        mandatory_ingredients=["Eggs"]
    )
    assert eval_accepted["outcome"] == "ACCEPTED"
    assert eval_accepted["match_ratio"] == 1.0
    assert eval_accepted["mandatory_met"] is True

    # 4. Mandatory ingredient requested but missing -> FLAGGED
    eval_missing_mandatory = logic_manager.evaluate_recipe(
        recipe={
            "recipe_name": "Toast with Butter",
            "estimated_cook_time_mins": 5,
            "ingredients_used": ["Bread"],
            "missing_ingredients": []
        },
        inventory=inventory,
        max_cook_time_mins=15,
        user_allergies=[],
        mandatory_ingredients=["Eggs"]
    )
    assert eval_missing_mandatory["outcome"] == "FLAGGED"
    assert eval_missing_mandatory["status_code"] == "MISSING_MANDATORY_INGREDIENT"
    assert "Eggs" in eval_missing_mandatory["missing_mandatory"]

    # 5. Multi-condition rule: REJECTED due to allergen
    eval_rejected_allergen = logic_manager.evaluate_recipe(
        recipe={
            "recipe_name": "Cheese Delight",
            "estimated_cook_time_mins": 10,
            "ingredients_used": ["Cheddar Cheese"],
            "missing_ingredients": []
        },
        inventory=inventory,
        max_cook_time_mins=15,
        user_allergies=["dairy"]
    )
    assert eval_rejected_allergen["outcome"] == "REJECTED"
    assert eval_rejected_allergen["status_code"] == "ALLERGEN_CONTAMINATION"

    # 6. Multi-condition rule: FLAGGED due to cooking time
    eval_flagged_time = logic_manager.evaluate_recipe(
        recipe={
            "recipe_name": "Slow Baked Eggs",
            "estimated_cook_time_mins": 45,
            "ingredients_used": ["Eggs"],
            "missing_ingredients": []
        },
        inventory=inventory,
        max_cook_time_mins=20,
        user_allergies=[]
    )
    assert eval_flagged_time["outcome"] == "FLAGGED"
    assert eval_flagged_time["status_code"] == "EXCEEDS_TIME_LIMIT"

    # 7. Multi-condition rule: FLAGGED due to missing ingredient with sufficient match ratio
    eval_flagged_missing = logic_manager.evaluate_recipe(
        recipe={
            "recipe_name": "Egg Mayo Toast",
            "estimated_cook_time_mins": 10,
            "ingredients_used": ["Eggs", "Bread"],
            "missing_ingredients": ["Mayonnaise"]
        },
        inventory=inventory,
        max_cook_time_mins=15,
        user_allergies=[]
    )
    assert eval_flagged_missing["outcome"] == "FLAGGED"
    assert eval_flagged_missing["status_code"] == "MISSING_SOME_INGREDIENTS"

    return True


def run_all_tests() -> None:
    """
    Executes all verification suites procedurally.
    """
    tests = [
        ("Zero Classes Constraint Check", test_zero_classes_in_codebase),
        ("Print() Localization Check", test_no_prints_outside_io_manager),
        ("Data Manager Persistence & Resilience", test_data_manager_operations),
        ("AI Manager Schema Validation", test_ai_manager_schema_validation),
        ("Logic Manager Multi-Condition Business Rules", test_logic_manager_rules),
    ]

    print("\n" + "=" * 60)
    print("RUNNING AUTOMATED VERIFICATION SUITE")
    print("=" * 60)

    import traceback
    passed_count = 0
    for name, func in tests:
        try:
            func()
            print(f"[PASS] {name}")
            passed_count += 1
        except Exception as e:
            print(f"[FAIL] {name} -> {e}")
            traceback.print_exc()

    print("=" * 60)
    print(f"Results: {passed_count}/{len(tests)} tests passed.")
    print("=" * 60)

    if passed_count != len(tests):
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
