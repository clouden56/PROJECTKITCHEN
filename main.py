"""
Main Application Coordinator
Responsibility: Orchestrates the 4-layer pipeline:
User / file -> io_manager -> ai_manager -> logic_manager -> data_manager
Constraints: 100% procedural (no classes); all terminal I/O is delegated to io_manager.
"""

import os
import logging
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

    if removed and data_manager.save_inventory(updated_inv, inventory_file):
        io_manager.display_message(f"Successfully removed '{target}' from inventory.", "success")
    elif removed:
        io_manager.display_message("Failed to save inventory to storage. No changes were made.", "error")
    else:
        io_manager.display_message(f"Ingredient '{target}' was not found in inventory.", "warning")

    io_manager.prompt_continue()


def handle_generate_recipe(inventory_file: str, history_file: str) -> None:
    """
    One record through the pipeline, growing at each stage:
    1. io_manager      -> typed request record (meal, time limit, allergies, must-haves)
    2. data_manager    -> + current inventory
    3. ai_manager      -> + validated AI recipe (every request goes through the API)
    4. logic_manager   -> + evaluation (business rules, score, route)
    5. data_manager    -> appended to recipe history
    6. io_manager      -> recipe card and verdict
    """
    inventory = data_manager.load_inventory(inventory_file)

    if len(inventory) < 2:
        io_manager.display_message(
            "You have less than 2 ingredients recorded. Please add more items to your inventory "
            "so the AI can suggest meaningful meals.",
            "warning"
        )
        io_manager.prompt_continue()
        return

    record = io_manager.prompt_recipe_generation_criteria()
    record["inventory"] = inventory

    io_manager.display_message(
        "Consulting Gemini AI with your inventory and expiry constraints... Please wait.",
        "info"
    )

    success, recipe, error_msg = ai_manager.process(record)
    if not success:
        io_manager.display_message(f"AI Generation Error: {error_msg}", "error")
        io_manager.prompt_continue()
        return

    record["recipe"] = recipe
    evaluation = logic_manager.evaluate(record)

    saved = data_manager.save(
        {
            "recipe": recipe,
            "evaluation": evaluation,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        history_file
    )

    io_manager.display_recipe_card(recipe, evaluation)
    if not saved:
        io_manager.display_message("Recipe could not be saved to history (storage error).", "warning")
    io_manager.prompt_continue()


def handle_view_history(history_file: str) -> None:
    """
    Views recipe history, optionally filtered via data_manager.query().
    """
    if not data_manager.load(history_file):
        io_manager.display_message("Recipe history is empty.", "info")
        io_manager.prompt_continue()
        return

    request = io_manager.prompt_history_filter()
    if request["mode"] == "meal_type":
        records = data_manager.query(data_manager.meal_type_filter(request["value"]), history_file)
    elif request["mode"] == "ingredient":
        records = data_manager.query(data_manager.ingredient_filter(request["value"]), history_file)
    else:
        records = data_manager.load(history_file)

    io_manager.display_recipe_history(records)
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
    saved_recipes = data_manager.load(history_file)
    io_manager.display_message(f"Loaded {len(saved_recipes)} saved recipe(s) from {history_file}.", "info")

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


def configure_logging(log_file: str = "data/app.log") -> None:
    """
    Routes diagnostic logs from all managers to a file so they never interleave with the
    terminal UI. If the file cannot be opened, logs are discarded rather than crashing.
    """
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            encoding="utf-8"
        )
    except OSError:
        logging.getLogger().addHandler(logging.NullHandler())


def main() -> None:
    """
    Entry point: runs the application and exits cleanly on Ctrl+C or closed input stream
    (e.g. running the container without -it) instead of printing a traceback.
    """
    configure_logging()
    try:
        run_application()
    except (KeyboardInterrupt, EOFError):
        io_manager.display_message("Input stream closed. Exiting Fridge Recipe Tracker safely.", "info")


if __name__ == "__main__":
    main()

