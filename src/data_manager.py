"""
Data Manager Module
Responsibility: Flat-file persistence, loading, saving, querying, and error recovery.
Architecture Layer: Data Layer
Constraints: 100% procedural (NO classes), NO print() statements.
"""

import os
import json
import logging
from datetime import datetime
from typing import Any

# Configure logger for headless error tracking
logger = logging.getLogger("data_manager")


def load_json_data(file_path: str, default_data: Any) -> Any:
    """
    Safely loads JSON data from a given file path.
    If the file does not exist, is empty, or is corrupted, it returns default_data
    and ensures the directory exists without crashing.
    """
    if not os.path.exists(file_path):
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as err:
                logger.error("Failed to create directory %s: %s", directory, err)
        return default_data

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read().strip()
            if not content:
                return default_data
            return json.loads(content)
    except (json.JSONDecodeError, OSError) as err:
        logger.error("Error reading %s: %s. Returning default fallback.", file_path, err)
        return default_data


def save_json_data(file_path: str, data: Any) -> bool:
    """
    Saves python data structure into JSON flat file.
    Creates parent directories if necessary.
    Returns True if successful, False otherwise.
    """
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as err:
            logger.error("Failed to create directory %s: %s", directory, err)
            return False

    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        return True
    except OSError as err:
        logger.error("Error writing JSON to %s: %s", file_path, err)
        return False


def load_inventory(file_path: str = "data/inventory.json") -> list[dict]:
    """
    Loads fridge and pantry inventory records from disk.
    """
    data = load_json_data(file_path, default_data=[])
    if isinstance(data, list):
        return data
    return []


def save_inventory(inventory: list[dict], file_path: str = "data/inventory.json") -> bool:
    """
    Persists inventory records to disk.
    """
    return save_json_data(file_path, inventory)


def add_inventory_item(inventory: list[dict], item: dict) -> list[dict]:
    """
    Appends or updates an inventory item by name.
    Returns the updated inventory list.
    """
    updated = list(inventory)
    target_name = item.get("name", "").strip().lower()
    existing_idx = -1

    for idx, existing in enumerate(updated):
        if existing.get("name", "").strip().lower() == target_name:
            existing_idx = idx
            break

    if existing_idx >= 0:
        # Update quantity and expiry date
        updated[existing_idx]["quantity"] = item.get("quantity", updated[existing_idx].get("quantity"))
        updated[existing_idx]["unit"] = item.get("unit", updated[existing_idx].get("unit"))
        updated[existing_idx]["expiry_date"] = item.get("expiry_date", updated[existing_idx].get("expiry_date"))
        updated[existing_idx]["location"] = item.get("location", updated[existing_idx].get("location"))
    else:
        if "id" not in item:
            item["id"] = f"ing-{len(updated) + 1:03d}"
        updated.append(item)

    return updated


def remove_inventory_item(inventory: list[dict], item_name: str) -> tuple[list[dict], bool]:
    """
    Removes an item from inventory by name (case-insensitive).
    Returns a tuple of (updated_inventory, was_removed).
    """
    clean_name = item_name.strip().lower()
    initial_count = len(inventory)
    updated = [item for item in inventory if item.get("name", "").strip().lower() != clean_name]
    was_removed = len(updated) < initial_count
    return updated, was_removed


def load_recipe_history(file_path: str = "data/recipe_history.json") -> list[dict]:
    """
    Loads saved recipe records from disk.
    """
    data = load_json_data(file_path, default_data=[])
    if isinstance(data, list):
        return data
    return []


def save_recipe_to_history(recipe_record: dict, file_path: str = "data/recipe_history.json") -> bool:
    """
    Appends an evaluated recipe record to persistent history.
    """
    history = load_recipe_history(file_path)
    history.append(recipe_record)
    return save_json_data(file_path, history)


def query_items_by_expiry(inventory: list[dict], max_days: int) -> list[dict]:
    """
    Filters inventory items that expire within max_days from today.
    Items with invalid or missing dates are placed at the end.
    """
    today = datetime.now().date()
    expiring_items = []

    for item in inventory:
        expiry_str = item.get("expiry_date", "")
        try:
            exp_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            days_left = (exp_date - today).days
            if days_left <= max_days:
                item_copy = dict(item)
                item_copy["days_left"] = days_left
                expiring_items.append(item_copy)
        except (ValueError, TypeError):
            continue

    expiring_items.sort(key=lambda x: x.get("days_left", 999))
    return expiring_items


def filter_recipes_by_meal_type(history: list[dict], meal_type: str) -> list[dict]:
    """
    Filters saved recipes by meal type (e.g., Breakfast, Lunch, Dinner, Snack).
    Supports both nested record structure and flat recipe dicts.
    """
    target = meal_type.strip().lower()
    results = []
    for r in history:
        recipe_data = r.get("recipe", r) if isinstance(r.get("recipe"), dict) else r
        val = recipe_data.get("meal_type", "").strip().lower()
        if val == target:
            results.append(r)
    return results


def search_recipes_by_ingredient(history: list[dict], ingredient_query: str) -> list[dict]:
    """
    Searches saved recipes for those containing the given ingredient.
    Supports both nested record structure and flat recipe dicts.
    """
    query = ingredient_query.strip().lower()
    results = []
    for r in history:
        recipe_data = r.get("recipe", r) if isinstance(r.get("recipe"), dict) else r
        used = [str(ing).lower() for ing in recipe_data.get("ingredients_used", [])]
        if any(query in ing for ing in used):
            results.append(r)
    return results


def query_items_by_storage(inventory: list[dict], storage_type: str) -> list[dict]:
    """
    Filters inventory items by storage location (e.g. 'Fridge' or 'Pantry').
    """
    target = storage_type.strip().lower()
    return [item for item in inventory if item.get("location", "").strip().lower() == target]
