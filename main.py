"""
Main Application Coordinator
Responsibility: Orchestrates the 4-layer pipeline:
User / file -> io_manager -> ai_manager -> logic_manager -> data_manager
Constraints: 100% procedural (NO classes), NO print() calls (delegates all output to io_manager).
"""

from datetime import datetime
from src import io_manager
from src import ai_manager
from src import logic_manager
from src import data_manager


def handle_view_inventory(inventory_file: str) -> None:
    """
    Loads inventory records via data_manager and renders them via io_manager.
    """
    inventory = data_manager.load_inventory(inventory_file)
    io_manager.display_inventory(inventory)
    io_manager.prompt_continue()


def handle_add_item(inventory_file: str) -> None:
    """
    Prompts user for item data via io_manager, updates inventory via data_manager.
    """
    new_item = io_manager.prompt_new_ingredient()
    inventory = data_manager.load_inventory(inventory_file)
    updated_inventory = data_manager.add_inventory_item(inventory, new_item)

    if data_manager.save_inventory(updated_inventory, inventory_file):
        io_manager.display_message(f"'{new_item['name']}' has been added/updated successfully.", "success")
    else:
        io_manager.display_message("Failed to save inventory to storage.", "error")

    io_manager.prompt_continue()


def handle_remove_item(inventory_file: str) -> None:
    """
    Prompts user for item name and removes it from inventory.
    """
    inventory = data_manager.load_inventory(inventory_file)
    if not inventory:
        io_manager.display_message("Inventory is already empty.", "warning")
        io_manager.prompt_continue()
        return

    io_manager.display_inventory(inventory)
    target = io_manager.prompt_string("Enter the name of the ingredient to remove")
    updated_inv, removed = data_manager.remove_inventory_item(inventory, target)

    if removed:
        data_manager.save_inventory(updated_inv, inventory_file)
        io_manager.display_message(f"Successfully removed '{target}' from inventory.", "success")
    else:
        io_manager.display_message(f"Ingredient '{target}' was not found in inventory.", "warning")

    io_manager.prompt_continue()


def handle_generate_recipe(inventory_file: str, history_file: str) -> None:
    """
    Pipeline Execution:
    1. Collect user constraints (io_manager)
    2. Check minimum inventory input (business validation)
    3. Call Gemini AI with structured schema (ai_manager)
    4. Apply multi-condition domain rules & scoring (logic_manager)
    5. Save evaluated record to flat-file storage (data_manager)
    6. Display formatted recipe card and verdict (io_manager)
    """
    inventory = data_manager.load_inventory(inventory_file)

    # Business rule: check minimum input
    if len(inventory) < 2:
        io_manager.display_message(
            "You have less than 2 ingredients recorded. Please add more items to your inventory "
            "so the AI can suggest meaningful meals.",
            "warning"
        )
        io_manager.prompt_continue()
        return

    # Collect parameters via io_manager
    criteria = io_manager.prompt_recipe_preferences_or_request = io_manager.prompt_recipe_generation_criteria()

    io_manager.display_message(
        "Consulting Gemini AI with your inventory and expiry constraints... Please wait.",
        "info"
    )

    # 1. AI Processing Layer: Call Gemini API and schema validation
    success, recipe, error_msg = ai_manager.request_recipe_from_ai(
        inventory=inventory,
        meal_type=criteria["meal_type"],
        max_cook_time_mins=criteria["max_cook_time_mins"],
        allergies=criteria["allergies"],
        additional_notes=criteria["additional_notes"]
    )

    if not success:
        io_manager.display_message(f"AI Generation Error: {error_msg}", "error")
        io_manager.prompt_continue()
        return

    # 2. Logic Layer: Evaluate multi-condition domain rules
    evaluation = logic_manager.evaluate_recipe(
        recipe=recipe,
        inventory=inventory,
        max_cook_time_mins=criteria["max_cook_time_mins"],
        user_allergies=criteria["allergies"]
    )

    # 3. Data Layer: Persist record to recipe history
    history_record = {
        "recipe": recipe,
        "evaluation": evaluation,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    data_manager.save_recipe_to_history(history_record, history_file)

    # 4. Input/Output Layer: Display recipe card
    io_manager.display_recipe_card(recipe, evaluation)
    io_manager.prompt_continue()


def handle_view_history(history_file: str) -> None:
    """
    Views or filters recipe history by meal type or ingredient.
    """
    history = data_manager.load_recipe_history(history_file)
    if not history:
        io_manager.display_message("Recipe history is empty.", "info")
        io_manager.prompt_continue()
        return

    io_manager.print_banner("Recipe History Explorer")
    io_manager.print_divider()
    choice = io_manager.prompt_string(
        "Filter by: [A]ll, [M]eal Type, [I]ngredient search (A/M/I)"
    ).upper()

    if choice == "M":
        meal = io_manager.prompt_meal_type()
        filtered = data_manager.filter_recipes_by_meal_type(history, meal)
        io_manager.display_recipe_history(filtered)
    elif choice == "I":
        ing = io_manager.prompt_string("Enter ingredient name to search for")
        filtered = data_manager.search_recipes_by_ingredient(history, ing)
        io_manager.display_recipe_history(filtered)
    else:
        io_manager.display_recipe_history(history)

    io_manager.prompt_continue()


def handle_view_expiring_soon(inventory_file: str) -> None:
    """
    Queries items expiring within 3 days and displays urgent rescue recommendations.
    """
    inventory = data_manager.load_inventory(inventory_file)
    urgent_items = data_manager.query_items_by_expiry(inventory, max_days=3)

    io_manager.print_banner("Items Requiring Urgent Cooking (<= 3 Days)")
    if not urgent_items:
        io_manager.display_message("Great news! You have no ingredients expiring within the next 3 days.", "success")
    else:
        io_manager.display_inventory(urgent_items)
        io_manager.display_message(
            f"Found {len(urgent_items)} urgent item(s). Use option [4] to let AI craft recipes with them!",
            "warning"
        )

    io_manager.prompt_continue()


def run_application(
    inventory_file: str = "data/inventory.json",
    history_file: str = "data/recipe_history.json"
) -> None:
    """
    Primary procedural execution loop.
    """
    io_manager.print_banner("Welcome to Fridge Recipe Tracker")
    io_manager.display_message("AI-Powered Sustainability & Meal Planner", "info")

    while True:
        io_manager.display_main_menu()
        choice = io_manager.prompt_menu_choice(min_val=1, max_val=7)

        if choice == 1:
            handle_view_inventory(inventory_file)
        elif choice == 2:
            handle_add_item(inventory_file)
        elif choice == 3:
            handle_remove_item(inventory_file)
        elif choice == 4:
            handle_generate_recipe(inventory_file, history_file)
        elif choice == 5:
            handle_view_history(history_file)
        elif choice == 6:
            handle_view_expiring_soon(inventory_file)
        elif choice == 7:
            io_manager.display_message("Thank you for using Fridge Recipe Tracker. Goodbye!", "info")
            break


if __name__ == "__main__":
    run_application()

