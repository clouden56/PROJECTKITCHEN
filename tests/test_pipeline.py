"""
Automated Verification Suite
Constraints: 100% procedural (NO classes anywhere, even in tests!), NO print() in core logic.
"""

import os
import sys
import json
import re
import io
import logging
import builtins
import contextlib
import tempfile
from datetime import datetime, timedelta

# Ensure src is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
from src import data_manager
from src import ai_manager
from src import logic_manager
from src import io_manager
from tests import sample_ai_responses as samples


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


def parse_sample(envelope: dict) -> dict:
    """
    Runs a hardcoded Gemini envelope through the real extraction + schema validation path.
    """
    valid, recipe, err = ai_manager.extract_recipe_json(envelope)
    assert valid is True, f"Sample AI response failed validation: {err}"
    return recipe


def test_logic_manager_with_sample_ai_responses() -> bool:
    """
    Feeds hardcoded sample AI responses through extract -> validate -> evaluate_recipe
    and checks every decision branch of the multi-condition rule.
    """
    inventory = samples.build_sample_inventory(datetime.now().date())

    accepted = logic_manager.evaluate_recipe(
        parse_sample(samples.SAMPLE_ACCEPTED), inventory, max_cook_time_mins=20, user_allergies=["nuts"]
    )
    assert accepted["outcome"] == "ACCEPTED", accepted["status_message"]
    assert accepted["status_code"] == "OPTIMAL_MATCH"
    assert accepted["match_ratio"] == 1.0
    assert accepted["expiry_priority_score"] == 100.0, "Spinach(0d)=40 + Eggs(1d)=30 + Cheddar(2d)=30"
    assert sorted(r["name"] for r in accepted["rescued_items"]) == ["Cheddar Cheese", "Eggs", "Spinach"]
    assert accepted["waste_diverted_grams"] == 950, "6 pcs x 100g + 200g + 150g"

    allergen = logic_manager.evaluate_recipe(
        parse_sample(samples.SAMPLE_DAIRY_ALLERGEN), inventory, max_cook_time_mins=30, user_allergies=["dairy"]
    )
    assert allergen["outcome"] == "REJECTED"
    assert allergen["status_code"] == "ALLERGEN_CONTAMINATION"
    assert allergen["allergen_safe"] is False

    insufficient = logic_manager.evaluate_recipe(
        parse_sample(samples.SAMPLE_INSUFFICIENT), inventory, max_cook_time_mins=180, user_allergies=[]
    )
    assert insufficient["outcome"] == "REJECTED"
    assert insufficient["status_code"] == "INSUFFICIENT_INGREDIENTS"
    assert insufficient["match_ratio"] < 0.5

    over_time = logic_manager.evaluate_recipe(
        parse_sample(samples.SAMPLE_OVER_TIME), inventory, max_cook_time_mins=30, user_allergies=[]
    )
    assert over_time["outcome"] == "FLAGGED"
    assert over_time["status_code"] == "EXCEEDS_TIME_LIMIT"
    assert over_time["is_within_time"] is False

    missing_some = logic_manager.evaluate_recipe(
        parse_sample(samples.SAMPLE_MISSING_SOME), inventory, max_cook_time_mins=30, user_allergies=[]
    )
    assert missing_some["outcome"] == "FLAGGED"
    assert missing_some["status_code"] == "MISSING_SOME_INGREDIENTS"
    assert missing_some["match_ratio"] == 0.6

    missing_mandatory = logic_manager.evaluate_recipe(
        parse_sample(samples.SAMPLE_ACCEPTED), inventory, max_cook_time_mins=20, user_allergies=[],
        mandatory_ingredients=["Chicken Breast"]
    )
    assert missing_mandatory["outcome"] == "FLAGGED"
    assert missing_mandatory["status_code"] == "MISSING_MANDATORY_INGREDIENT"
    assert missing_mandatory["missing_mandatory"] == ["Chicken Breast"]

    return True


def test_logic_manager_helper_functions() -> bool:
    """
    Unit-tests the individual logic_manager building blocks with fixed reference dates.
    """
    ref = datetime(2026, 10, 8).date()
    assert logic_manager.calculate_days_until_expiry("2026-10-10", ref) == 2
    assert logic_manager.calculate_days_until_expiry("2026-10-08", ref) == 0
    assert logic_manager.calculate_days_until_expiry("2026-10-01", ref) == -7
    assert logic_manager.calculate_days_until_expiry("10/12/2026", ref) == 999, "Malformed date is non-urgent"
    assert logic_manager.calculate_days_until_expiry("", ref) == 999
    assert logic_manager.calculate_days_until_expiry(None, ref) == 999

    assert logic_manager.does_ingredient_match("2 large eggs", "Eggs") is True
    assert logic_manager.does_ingredient_match("Tomatoes", "tomato") is True
    assert logic_manager.does_ingredient_match("Chicken Breast", "Bread") is False

    ratio, matched, missing = logic_manager.calculate_ingredient_match_ratio(
        {"ingredients_used": ["Eggs", "Bread"], "missing_ingredients": ["Salt", "Black Pepper"]},
        [{"name": "Eggs"}, {"name": "Bread"}]
    )
    assert ratio == 1.0, "Pantry staples (salt, pepper) must not lower the match ratio"
    assert matched == ["Eggs", "Bread"]
    assert "Salt" in missing, "Staples are still reported to the user"

    grams = logic_manager.estimate_food_waste_diverted([
        {"days_until_expiry": 1, "quantity": 0.5, "unit": "kg"},
        {"days_until_expiry": 2, "quantity": 250, "unit": "ml"},
        {"days_until_expiry": 0, "quantity": "two", "unit": "pcs"},
        {"days_until_expiry": 6, "quantity": 999, "unit": "g"},
    ])
    assert grams == 500 + 250 + 100, "kg->g, ml~g, unparseable qty defaults to 1 unit, >3 days ignored"

    met, missing_req = logic_manager.check_mandatory_ingredients(
        {"ingredients_used": ["3 Eggs", "Spinach"]}, ["eggs", "Bacon", "  "]
    )
    assert met is False and missing_req == ["Bacon"]

    is_safe, hits = logic_manager.evaluate_allergen_safety(
        {"ingredients_used": ["Garlic Prawns"], "missing_ingredients": []}, ["shellfish"]
    )
    assert is_safe is False and hits, "Synonym map must catch prawn as shellfish"

    return True


def test_ai_manager_rejects_malformed_responses() -> bool:
    """
    Every malformed sample response must be rejected with an error message, never an exception.
    A fenced-but-valid response must still be accepted.
    """
    for label, envelope in samples.ALL_MALFORMED_RESPONSES.items():
        valid, recipe, err = ai_manager.extract_recipe_json(envelope)
        assert valid is False, f"Malformed response accepted: {label}"
        assert recipe == {} and err, f"Expected empty recipe and error message for: {label}"

    valid, recipe, err = ai_manager.extract_recipe_json(samples.SAMPLE_FENCED_JSON)
    assert valid is True, f"Markdown-fenced JSON should be accepted: {err}"
    assert recipe["recipe_name"] == "Cheese Toast"

    bool_time = json.loads(samples.SAMPLE_ACCEPTED["candidates"][0]["content"]["parts"][0]["text"])
    bool_time["estimated_cook_time_mins"] = True
    assert ai_manager.validate_recipe_schema(bool_time)[0] is False, "bool is not a valid cook time"

    return True


def test_ai_pipeline_offline_failure_handling() -> bool:
    """
    Simulates API connection failures and malformed responses by substituting call_gemini_api,
    proving request_recipe_from_ai degrades gracefully. No live API connection is used.
    """
    original_call = ai_manager.call_gemini_api
    original_sleep = ai_manager.time.sleep
    original_key = os.environ.get("GEMINI_API_KEY")
    original_base_url = ai_manager.API_BASE_URL
    original_urlopen = ai_manager.urllib.request.urlopen
    calls = []

    def run_with_responses(responses: list[tuple]) -> tuple[bool, dict, str]:
        calls.clear()
        queue = list(responses)

        def fake_call(prompt: str, api_key: str, model: str = ai_manager.DEFAULT_MODEL, timeout_seconds: int = 30):
            calls.append(model)
            return queue.pop(0) if queue else responses[-1]

        ai_manager.call_gemini_api = fake_call
        return ai_manager.request_recipe_from_ai(
            inventory=samples.build_sample_inventory(datetime.now().date()),
            meal_type="Breakfast", max_cook_time_mins=20, allergies=[]
        )

    try:
        ai_manager.time.sleep = lambda seconds: None
        os.environ["GEMINI_API_KEY"] = "offline-test-key"

        # 1. Network down: every model retried, then a clean failure message
        ok, recipe, msg = run_with_responses([(False, None, "Network connection error: [Errno 11001] getaddrinfo failed")])
        assert ok is False and recipe == {}
        assert "temporarily unavailable" in msg
        assert len(calls) == 2 * len(ai_manager.MODELS_CASCADE), "Expected 2 attempts per cascade model"

        # 2. Invalid API key: abort immediately, no pointless retries
        ok, _, msg = run_with_responses([(False, None, 'HTTP Error 400: Bad Request - {"reason": "API_KEY_INVALID"}')])
        assert ok is False and "GEMINI_API_KEY" in msg
        assert len(calls) == 1

        # 3. Model not found: skip to the next model in the cascade, which succeeds
        ok, recipe, _ = run_with_responses([
            (False, None, "HTTP Error 404: Not Found - model retired"),
            (True, samples.SAMPLE_ACCEPTED, ""),
        ])
        assert ok is True and recipe["recipe_name"] == "Spinach & Cheddar Omelette"
        assert calls == ai_manager.MODELS_CASCADE[:2]

        # 4. Malformed AI response, then a valid one on retry
        ok, recipe, _ = run_with_responses([
            (True, samples.MALFORMED_PROSE_NOT_JSON, ""),
            (True, samples.SAMPLE_MISSING_SOME, ""),
        ])
        assert ok is True and recipe["recipe_name"] == "French Toast"
        assert len(calls) == 2

        # 5. Rate limited (429) then recovers
        ok, _, _ = run_with_responses([
            (False, None, "HTTP Error 429: Too Many Requests - quota"),
            (True, samples.SAMPLE_ACCEPTED, ""),
        ])
        assert ok is True and len(calls) == 2

        # 6. Missing API key: fails fast before any network call
        os.environ["GEMINI_API_KEY"] = ""
        ok, _, msg = run_with_responses([(True, samples.SAMPLE_ACCEPTED, "")])
        assert ok is False and "not configured" in msg
        assert calls == [], "No API call should be attempted without a key"

        # 7. Real HTTP code path against a closed local port: URLError is caught, not raised
        ai_manager.call_gemini_api = original_call
        ai_manager.API_BASE_URL = "http://127.0.0.1:9/v1beta/models"
        ok, raw, msg = ai_manager.call_gemini_api("prompt", "offline-test-key", timeout_seconds=5)
        assert ok is False and raw is None
        assert msg.startswith(("Network connection error", "Network timeout", "Unexpected error"))

        # 8. Timeout and non-JSON / non-object HTTP bodies, via a substituted urlopen
        def raise_timeout(*args, **kwargs):
            raise TimeoutError("timed out")

        ai_manager.urllib.request.urlopen = raise_timeout
        ok, _, msg = ai_manager.call_gemini_api("prompt", "offline-test-key")
        assert ok is False and msg.startswith("Network timeout")
        assert ai_manager.classify_api_error(msg) == "retry"

        ai_manager.urllib.request.urlopen = lambda *a, **k: io.BytesIO(b"<html>502 Bad Gateway</html>")
        ok, _, msg = ai_manager.call_gemini_api("prompt", "offline-test-key")
        assert ok is False and "parse API HTTP response" in msg

        ai_manager.urllib.request.urlopen = lambda *a, **k: io.BytesIO(b"[1, 2, 3]")
        ok, _, msg = ai_manager.call_gemini_api("prompt", "offline-test-key")
        assert ok is False and "not an object" in msg
    finally:
        ai_manager.urllib.request.urlopen = original_urlopen
        ai_manager.call_gemini_api = original_call
        ai_manager.time.sleep = original_sleep
        ai_manager.API_BASE_URL = original_base_url
        if original_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = original_key

    return True


def test_data_manager_corrupt_and_unwritable_files() -> bool:
    """
    Corrupt files are quarantined (not silently overwritten), wrong-shaped JSON is ignored,
    saves are atomic, and write failures return False instead of crashing.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        inv_file = os.path.join(tmp_dir, "inventory.json")

        with open(inv_file, "w", encoding="utf-8") as f:
            f.write('[{"name": "Milk", "quantity": 1')
        assert data_manager.load_inventory(inv_file) == []
        backups = [n for n in os.listdir(tmp_dir) if ".corrupt-" in n]
        assert len(backups) == 1, "Corrupt file must be backed up for recovery"
        assert not os.path.exists(inv_file), "Corrupt file moved aside so next save starts clean"
        with open(os.path.join(tmp_dir, backups[0]), "r", encoding="utf-8") as f:
            assert "Milk" in f.read(), "Original bytes preserved in backup"

        with open(inv_file, "w", encoding="utf-8") as f:
            f.write("   \n")
        assert data_manager.load_inventory(inv_file) == [], "Empty file treated as empty inventory"

        with open(inv_file, "w", encoding="utf-8") as f:
            json.dump({"name": "not a list"}, f)
        assert data_manager.load_inventory(inv_file) == []

        with open(inv_file, "w", encoding="utf-8") as f:
            json.dump([{"name": "Eggs"}, "garbage", 42, None], f)
        assert data_manager.load_inventory(inv_file) == [{"name": "Eggs"}]

        assert data_manager.save_inventory([{"name": "Rice"}], inv_file) is True
        assert not os.path.exists(inv_file + ".tmp"), "Temp file must be renamed into place"
        assert data_manager.load_inventory(inv_file) == [{"name": "Rice"}]

        unwritable = os.path.join(inv_file, "nested.json")
        assert data_manager.save_inventory([{"name": "Rice"}], unwritable) is False

        assert data_manager.save_inventory([{"bad": {1, 2}}], os.path.join(tmp_dir, "y.json")) is False, \
            "Unserialisable data must return False"
        assert not os.path.exists(os.path.join(tmp_dir, "y.json.tmp")), "Failed write must clean up temp file"

    return True


def make_fake_input(values: list[str]):
    """
    Returns an input() replacement that yields scripted keystrokes, then raises EOFError
    (the same signal a closed terminal/pipe produces).
    """
    queue = list(values)

    def fake_input(prompt: str = "") -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return fake_input


def run_with_scripted_input(values: list[str], func, *args, **kwargs):
    """
    Calls func with builtins.input replaced by scripted keystrokes and terminal output discarded.
    """
    original_input = builtins.input
    builtins.input = make_fake_input(values)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return func(*args, **kwargs)
    finally:
        builtins.input = original_input


def test_io_manager_reprompts_invalid_input() -> bool:
    """
    Every io_manager prompt must reject invalid keystrokes and keep asking until valid.
    """
    assert run_with_scripted_input(["", "abc", "9", "0", "3"], io_manager.prompt_menu_choice, 1, 7) == 3
    assert run_with_scripted_input(["", "   ", "Eggs"], io_manager.prompt_string, "Name") == "Eggs"
    assert run_with_scripted_input(
        ["2026/10/12", "2026-02-30", "tomorrow", "2026-10-12"], io_manager.prompt_date, "Expiry"
    ) == "2026-10-12"
    assert run_with_scripted_input(
        ["-1", "0", "abc", "inf", "nan", "2.5"], io_manager.prompt_positive_number, "Qty", True
    ) == 2.5
    assert run_with_scripted_input(["1.5", "-30", "30"], io_manager.prompt_positive_number, "Mins") == 30
    assert run_with_scripted_input(["5", "x", "3"], io_manager.prompt_meal_type) == "Dinner"
    assert run_with_scripted_input(["3", "", "2"], io_manager.prompt_storage_location) == "Pantry"
    assert run_with_scripted_input(["peanuts, , dairy "], io_manager.prompt_allergies) == ["peanuts", "dairy"]
    return True


def test_end_to_end_pipeline_offline() -> bool:
    """
    Drives the real CLI (main.run_application) with scripted keystrokes through the full data flow:
    keystrokes -> validated input -> AI payload (sample response, no network) -> logic evaluation
    -> flat-file storage. Also checks Ctrl+C/EOF exits cleanly.
    """
    original_call = ai_manager.call_gemini_api
    original_key = os.environ.get("GEMINI_API_KEY")
    original_logging = main.configure_logging
    payloads = []

    def fake_call(prompt: str, api_key: str, model: str = ai_manager.DEFAULT_MODEL, timeout_seconds: int = 30):
        payloads.append(prompt)
        return True, samples.SAMPLE_ACCEPTED, ""

    with tempfile.TemporaryDirectory() as tmp_dir:
        inv_file = os.path.join(tmp_dir, "inventory.json")
        hist_file = os.path.join(tmp_dir, "recipe_history.json")
        data_manager.save_inventory(samples.build_sample_inventory(datetime.now().date()), inv_file)

        try:
            ai_manager.call_gemini_api = fake_call
            os.environ["GEMINI_API_KEY"] = "offline-test-key"
            main.configure_logging = lambda log_file="": None

            # Option 2: add a new item (with one invalid quantity retyped), then exit
            run_with_scripted_input(
                ["2", "Tofu", "1", "zero", "300", "g", "12-10-2026", "2026-10-20", "", "7"],
                main.run_application, inv_file, hist_file
            )
            inventory = data_manager.load_inventory(inv_file)
            tofu = [i for i in inventory if i["name"] == "Tofu"]
            assert tofu and tofu[0]["quantity"] == 300.0 and tofu[0]["expiry_date"] == "2026-10-20"
            assert tofu[0]["id"] == "ing-007"

            # Option 3: removing an unknown item leaves the file unchanged
            run_with_scripted_input(["3", "Ghost Pepper", "", "7"], main.run_application, inv_file, hist_file)
            assert data_manager.load_inventory(inv_file) == inventory

            # Option 4: generate a recipe (Breakfast, 20 mins, allergic to nuts), then exit
            run_with_scripted_input(["4", "1", "20", "nuts", "", "", "", "7"], main.run_application, inv_file, hist_file)
            assert len(payloads) == 1 and "Spinach" in payloads[0] and "nuts" in payloads[0]
            history = data_manager.load_recipe_history(hist_file)
            assert len(history) == 1
            assert history[0]["recipe"]["recipe_name"] == "Spinach & Cheddar Omelette"
            assert history[0]["evaluation"]["outcome"] == "ACCEPTED"
            assert "created_at" in history[0]

            # API failure: nothing is written to history and the app returns to the menu
            ai_manager.call_gemini_api = lambda *a, **k: (False, None, "HTTP Error 401: Unauthorized")
            run_with_scripted_input(["4", "2", "30", "", "", "", "", "7"], main.run_application, inv_file, hist_file)
            assert len(data_manager.load_recipe_history(hist_file)) == 1

            # Input stream closed at the menu prompt: main() exits without raising
            run_with_scripted_input([], main.main)
        finally:
            ai_manager.call_gemini_api = original_call
            main.configure_logging = original_logging
            if original_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = original_key

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
        ("Logic Manager Rules on Sample AI Responses", test_logic_manager_with_sample_ai_responses),
        ("Logic Manager Helper Functions", test_logic_manager_helper_functions),
        ("AI Manager Rejects Malformed Responses", test_ai_manager_rejects_malformed_responses),
        ("AI Pipeline Offline Failure Handling", test_ai_pipeline_offline_failure_handling),
        ("Data Manager Corrupt & Unwritable Files", test_data_manager_corrupt_and_unwritable_files),
        ("IO Manager Re-prompts Invalid Input", test_io_manager_reprompts_invalid_input),
        ("End-to-End Pipeline (Offline, Scripted Input)", test_end_to_end_pipeline_offline),
    ]

    # Failure-path tests trigger expected error logs; silence them so the report stays readable
    logging.disable(logging.CRITICAL)

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
