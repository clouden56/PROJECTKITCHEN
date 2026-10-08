"""
Data Manager Module
Responsibility: Flat-file persistence, loading, saving, querying, and error recovery.
Architecture Layer: Data Layer
Framework functions: save(record), load(), query(filter_fn) for evaluated recipe records;
load_inventory/save_inventory for the inventory the requests are built from.
Constraints: 100% procedural (no classes), no terminal I/O.
"""

import os
import json
import logging
from datetime import datetime
from typing import Any, Callable

# Configure logger for headless error tracking
logger = logging.getLogger("data_manager")

INVENTORY_FILE = "data/inventory.json"
HISTORY_FILE = "data/recipe_history.json"


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
    except (OSError, UnicodeDecodeError) as err:
        logger.error("Error reading %s: %s. Returning default fallback.", file_path, err)
        return default_data

    if not content:
        return default_data

    try:
        return json.loads(content)
    except json.JSONDecodeError as err:
        logger.error("Corrupt JSON in %s: %s. Returning default fallback.", file_path, err)
        quarantine_corrupt_file(file_path)
        return default_data


def quarantine_corrupt_file(file_path: str) -> str:
    """
    Moves a corrupt data file aside to '<name>.corrupt-<timestamp>.bak' so the next save
    starts clean without destroying the original bytes (kept for manual recovery).
    Returns the backup path, or "" if the move failed.
    """
    backup_path = f"{file_path}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
    try:
        os.replace(file_path, backup_path)
        logger.warning("Corrupt file %s backed up to %s", file_path, backup_path)
        return backup_path
    except OSError as err:
        logger.error("Could not back up corrupt file %s: %s", file_path, err)
        return ""


def save_json_data(file_path: str, data: Any) -> bool:
    """
    Saves python data structure into JSON flat file.
    Creates parent directories if necessary. Writes to a temp file first and then
    atomically replaces the target, so an interrupted write cannot corrupt existing data.
    Returns True if successful, False otherwise.
    """
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as err:
            logger.error("Failed to create directory %s: %s", directory, err)
            return False

    temp_path = f"{file_path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        os.replace(temp_path, file_path)
        return True
    except (OSError, TypeError, ValueError) as err:
        logger.error("Error writing JSON to %s: %s", file_path, err)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def load_inventory(file_path: str = INVENTORY_FILE) -> list[dict]:
    """
    Loads fridge and pantry inventory records from disk.
    Non-list files and non-dict records are discarded so downstream layers can rely on the shape.
    """
    data = load_json_data(file_path, default_data=[])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    logger.error("Inventory file %s does not contain a JSON list. Using empty inventory.", file_path)
    return []


def save_inventory(inventory: list[dict], file_path: str = INVENTORY_FILE) -> bool:
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


def load(file_path: str = HISTORY_FILE) -> list[dict]:
    """
    Reads and returns every saved (AI-processed, evaluated) recipe record.
    Returns an empty list if the file is missing, empty or corrupt; never raises.
    """
    data = load_json_data(file_path, default_data=[])
    if isinstance(data, list):
        return [record for record in data if isinstance(record, dict)]
    logger.error("History file %s does not contain a JSON list. Using empty history.", file_path)
    return []


def save(record: dict, file_path: str = HISTORY_FILE) -> bool:
    """
    Appends one record to the history file after logic_manager has evaluated it.
    Returns True on success, False if the write failed.
    """
    history = load(file_path)
    history.append(record)
    return save_json_data(file_path, history)


def query(filter_fn: Callable[[dict], bool], file_path: str = HISTORY_FILE) -> list[dict]:
    """
    Returns the saved records for which filter_fn(record) is truthy. A record that makes the
    filter raise (e.g. a hand-edited row missing a field) is skipped and logged, not fatal.
    """
    matches = []
    for record in load(file_path):
        try:
            if filter_fn(record):
                matches.append(record)
        except (KeyError, TypeError, AttributeError, ValueError) as err:
            logger.warning("Skipping record that filter could not evaluate: %s", err)
    return matches


def recipe_of(record: dict) -> dict:
    """
    The recipe part of a history record (supports nested {"recipe": {...}} and flat recipe dicts).
    """
    return record["recipe"] if isinstance(record.get("recipe"), dict) else record


def meal_type_filter(meal_type: str) -> Callable[[dict], bool]:
    """
    Builds a query() filter matching records of the given meal type (case-insensitive).
    """
    target = meal_type.strip().lower()
    return lambda record: str(recipe_of(record).get("meal_type", "")).strip().lower() == target


def ingredient_filter(ingredient: str) -> Callable[[dict], bool]:
    """
    Builds a query() filter matching records whose recipe uses the given ingredient (substring).
    """
    needle = ingredient.strip().lower()
    return lambda record: any(needle in str(ing).lower() for ing in recipe_of(record).get("ingredients_used", []))


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


def query_items_by_storage(inventory: list[dict], storage_type: str) -> list[dict]:
    """
    Filters inventory items by storage location (e.g. 'Fridge' or 'Pantry').
    """
    target = storage_type.strip().lower()
    return [item for item in inventory if item.get("location", "").strip().lower() == target]
