"""
I/O Manager Module
Responsibility: All terminal user interfaces, structured user inputs, strict re-prompt validations,
formatting of inventory tables, recipe cards, and summary reports.
Architecture Layer: Input Layer
Constraints: 100% procedural (NO classes).
IMPORTANT: ALL print() calls in the entire application reside in this module and nowhere else.
"""

import sys
from datetime import datetime


def print_banner(title: str) -> None:
    """
    Renders an ASCII styled header banner.
    """
    line = "=" * 65
    print("\n" + line)
    print(f"   {title.upper()}")
    print(line)


def print_divider() -> None:
    """
    Renders a subtle visual separator.
    """
    print("-" * 65)


def display_message(message: str, level: str = "info") -> None:
    """
    Displays styled messages depending on level (info, success, warning, error).
    """
    prefix_map = {
        "info": "[INFO]",
        "success": "[SUCCESS]",
        "warning": "[WARNING]",
        "error": "[ERROR]"
    }
    prefix = prefix_map.get(level.lower(), "[INFO]")
    print(f"\n{prefix} {message}")


def display_main_menu() -> None:
    """
    Renders the primary navigation menu.
    """
    print("\n" + "=" * 50)
    print("      FRIDGE RECIPE TRACKER - MAIN MENU")
    print("=" * 50)
    print("  [1] View Fridge & Pantry Inventory")
    print("  [2] Add / Update Food Item")
    print("  [3] Remove Food Item")
    print("  [4] AI Recipe Generator (Based on Expiry & Time)")
    print("  [5] Search & View Recipe History")
    print("  [6] View Items Expiring Soon (Urgent Rescue)")
    print("  [7] Exit Application")
    print("=" * 50)


def prompt_menu_choice(min_val: int = 1, max_val: int = 7) -> int:
    """
    Prompts user for menu choice. Re-prompts continuously on invalid input.
    """
    while True:
        try:
            raw = input(f"Enter option [{min_val}-{max_val}]: ").strip()
            if not raw:
                print("Input cannot be empty. Please enter a valid number.")
                continue
            choice = int(raw)
            if min_val <= choice <= max_val:
                return choice
            print(f"Invalid option. Please choose between {min_val} and {max_val}.")
        except ValueError:
            print("Invalid input. Please enter a numeric digit.")


def prompt_string(label: str, allow_empty: bool = False) -> str:
    """
    Prompts for a text string, rejecting empty inputs if allow_empty is False.
    """
    while True:
        val = input(f"{label}: ").strip()
        if val or allow_empty:
            return val
        print("Value cannot be blank. Please enter a valid text.")


def prompt_positive_number(label: str, is_float: bool = False) -> float | int:
    """
    Prompts for a strictly positive number. Re-prompts on non-numeric or negative input.
    """
    while True:
        raw = input(f"{label}: ").strip()
        try:
            val = float(raw) if is_float else int(raw)
            if val > 0:
                return val
            print("Number must be strictly greater than 0.")
        except ValueError:
            expected = "a decimal number" if is_float else "a whole number"
            print(f"Invalid input. Please enter {expected}.")


def prompt_date(label: str) -> str:
    """
    Prompts for a date strictly in YYYY-MM-DD format. Re-prompts until valid.
    """
    while True:
        raw = input(f"{label} (YYYY-MM-DD): ").strip()
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            print("Invalid date format. Please use exactly YYYY-MM-DD (e.g., 2026-09-25).")


def prompt_storage_location() -> str:
    """
    Prompts user to select storage location.
    """
    print("\nSelect Storage Location:")
    print("  [1] Fridge")
    print("  [2] Pantry")
    while True:
        c = input("Choice [1-2]: ").strip()
        if c == "1":
            return "Fridge"
        if c == "2":
            return "Pantry"
        print("Invalid choice. Enter 1 for Fridge or 2 for Pantry.")


def prompt_meal_type() -> str:
    """
    Prompts user to select meal category.
    """
    print("\nSelect Desired Meal Type:")
    print("  [1] Breakfast")
    print("  [2] Lunch")
    print("  [3] Dinner")
    print("  [4] Snack")
    mapping = {"1": "Breakfast", "2": "Lunch", "3": "Dinner", "4": "Snack"}
    while True:
        c = input("Select [1-4]: ").strip()
        if c in mapping:
            return mapping[c]
        print("Invalid choice. Please select 1, 2, 3, or 4.")


def prompt_allergies() -> list[str]:
    """
    Prompts user for comma-separated allergies or dietary restrictions.
    """
    print("\nEnter any allergies or items to strictly avoid (comma-separated, e.g. peanuts, dairy, gluten).")
    raw = input("Allergies (or press Enter if none): ").strip()
    if not raw:
        return []
    return [a.strip() for a in raw.split(",") if a.strip()]


def prompt_new_ingredient() -> dict:
    """
    Collects complete structured data for an ingredient with input validation.
    """
    print_banner("Add New Item to Inventory")
    name = prompt_string("Ingredient Name (e.g. Eggs, Milk, Spinach)")
    location = prompt_storage_location()
    qty = prompt_positive_number("Quantity", is_float=True)
    unit = prompt_string("Unit of Measure (e.g. pcs, g, ml, slices, pack)")
    expiry = prompt_date("Expiry Date")

    return {
        "name": name,
        "location": location,
        "quantity": qty,
        "unit": unit,
        "expiry_date": expiry
    }


def prompt_recipe_generation_criteria() -> dict:
    """
    Gathers structured preferences from user for recipe generation.
    """
    print_banner("AI Recipe Recommendation Request")
    meal = prompt_meal_type()
    cook_time = prompt_positive_number("Maximum Cooking Time in minutes (e.g., 15, 30, 45)", is_float=False)
    allergies = prompt_allergies()
    notes = prompt_string("Any cooking style preferences? (e.g., stir-fry, soup, one-pot, or press Enter)", allow_empty=True)

    return {
        "meal_type": meal,
        "max_cook_time_mins": int(cook_time),
        "allergies": allergies,
        "additional_notes": notes
    }


def display_inventory(inventory: list[dict]) -> None:
    """
    Formats inventory items into an aligned table with expiry urgency badges.
    """
    print_banner("Current Fridge & Pantry Inventory")
    if not inventory:
        print("Your inventory is currently empty. Add items using option [2].")
        return

    today = datetime.now().date()
    header_fmt = "{:<6} | {:<20} | {:<12} | {:<10} | {:<12} | {:<15}"
    row_fmt    = "{:<6} | {:<20} | {:<12} | {:<10} | {:<12} | {:<15}"

    print(header_fmt.format("ID", "Item Name", "Quantity", "Location", "Expiry Date", "Status"))
    print_divider()

    for item in inventory:
        item_id = item.get("id", "N/A")
        name = item.get("name", "Unknown")
        qty_str = f"{item.get('quantity', 0)} {item.get('unit', '')}"
        loc = item.get("location", "Fridge")
        exp_str = item.get("expiry_date", "N/A")

        status_badge = "Fresh"
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            diff = (exp_date - today).days
            if diff < 0:
                status_badge = "[EXPIRED]"
            elif diff == 0:
                status_badge = "[EXPIRES TODAY]"
            elif diff <= 3:
                status_badge = f"[SOON ({diff}d)]"
            else:
                status_badge = f"OK ({diff}d left)"
        except (ValueError, TypeError):
            status_badge = "Unknown"

        print(row_fmt.format(item_id, name[:20], qty_str[:12], loc[:10], exp_str[:12], status_badge))

    print_divider()
    print(f"Total items tracked: {len(inventory)}")


def display_recipe_card(recipe: dict, evaluation: dict) -> None:
    """
    Renders a formatted card displaying the AI-generated recipe alongside
    the domain logic evaluation rules.
    """
    print_banner(f"Recipe: {recipe.get('recipe_name', 'Untitled')}")
    outcome = evaluation.get("outcome", "UNKNOWN")
    print(f"Outcome Status  : [{outcome}] - {evaluation.get('status_code', '')}")
    print(f"Evaluation Notes: {evaluation.get('status_message', '')}")
    print_divider()

    print(f"Meal Type       : {recipe.get('meal_type', 'Any')}")
    print(f"Est. Cook Time  : {recipe.get('estimated_cook_time_mins', 0)} minutes")
    print(f"Match Ratio     : {evaluation.get('match_percentage', 0)}% of required ingredients available")
    print(f"Expiry Priority : {evaluation.get('expiry_priority_score', 0)} / 100 (Urgency score)")
    print(f"Food Waste Saved: ~{evaluation.get('waste_diverted_grams', 0)} grams diverted from disposal")

    print("\nIngredients Used From Your Kitchen:")
    for ing in recipe.get("ingredients_used", []):
        print(f"  + {ing}")

    missing = recipe.get("missing_ingredients", [])
    if missing:
        print("\nMissing / Extra Ingredients Needed:")
        for m in missing:
            print(f"  - {m}")
    else:
        print("\nMissing Ingredients: None! You have everything required.")

    print("\nCooking Instructions:")
    for idx, step in enumerate(recipe.get("instructions", []), 1):
        print(f"  {idx}. {step}")

    notes = recipe.get("waste_reduction_notes", "")
    if notes:
        print(f"\nSustainability Tip: {notes}")

    rescued = evaluation.get("rescued_items", [])
    if rescued:
        print("\nNear-Expiry Ingredients Rescued:")
        for r in rescued:
            print(f"  * {r.get('name')} (Expires in {r.get('days_until_expiry')} days)")

    print_divider()


def display_recipe_history(history: list[dict]) -> None:
    """
    Renders historical recipe records.
    """
    print_banner("Saved Recipe History")
    if not history:
        print("No recipes have been saved to history yet.")
        return

    for idx, record in enumerate(history, 1):
        recipe = record.get("recipe", {})
        eval_data = record.get("evaluation", {})
        created_at = record.get("created_at", "N/A")

        print(f"\n[{idx}] {recipe.get('recipe_name', 'Unnamed Recipe')} (Saved on: {created_at})")
        print(f"    Meal Type    : {recipe.get('meal_type')} | Time: {recipe.get('estimated_cook_time_mins')} mins")
        print(f"    Match Ratio  : {eval_data.get('match_percentage', 0)}% | Outcome: {eval_data.get('outcome')}")
        print(f"    Ingredients  : {', '.join(recipe.get('ingredients_used', []))}")
        print("-" * 50)


def prompt_continue() -> None:
    """
    Pauses output until user presses Enter.
    """
    input("\nPress Enter to continue...")

