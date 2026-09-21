"""
AI Manager Module
Responsibility: Prompt construction, Gemini REST API communication, JSON schema validation, error recovery.
Architecture Layer: AI Processing Layer
Constraints: 100% procedural (NO classes), NO print() statements, ZERO domain logic.
"""

import os
import json
import urllib.request
import urllib.error
import logging
from typing import Any

logger = logging.getLogger("ai_manager")

DEFAULT_MODEL = "gemini-3.6-flash"
API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def load_env_file_if_present(env_path: str = ".env") -> None:
    """
    Lightweight procedural helper to load key-value pairs from .env
    into os.environ if not already set.
    """
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
    except OSError as err:
        logger.error("Could not read .env file: %s", err)


def get_api_key() -> str:
    """
    Retrieves the Gemini API key from environment variables or .env file.
    """
    load_env_file_if_present()
    return os.environ.get("GEMINI_API_KEY", "").strip()


def build_recipe_prompt(
    inventory_items: list[dict],
    meal_type: str,
    max_cook_time_mins: int,
    allergies: list[str],
    additional_notes: str = ""
) -> str:
    """
    Constructs a detailed structured prompt instructing the AI to output
    a valid JSON recipe maximizing the use of near-expiry ingredients.
    """
    items_desc = []
    for item in inventory_items:
        name = item.get("name", "Unknown")
        qty = item.get("quantity", "")
        unit = item.get("unit", "")
        expiry = item.get("expiry_date", "N/A")
        location = item.get("location", "Fridge")
        items_desc.append(f"- {name} ({qty} {unit}, Location: {location}, Expiry: {expiry})")

    items_text = "\n".join(items_desc) if items_desc else "No ingredients provided."
    allergies_text = ", ".join(allergies) if allergies else "None"

    prompt = f"""You are a professional culinary chef and food sustainability assistant.
The user has the following ingredients available in their fridge and pantry:
{items_text}

Constraints & Preferences:
- Meal Type: {meal_type}
- Target Max Cooking Time: {max_cook_time_mins} minutes
- User Allergies / Restrictions to avoid: {allergies_text}
- Additional Notes: {additional_notes if additional_notes else "Prioritize using ingredients expiring soonest."}

Generate an optimal recipe that maximizes usage of available ingredients (especially those expiring soonest) and minimizes food waste.

You MUST respond strictly with a valid JSON object conforming to this schema:
{{
  "recipe_name": "string (name of dish)",
  "meal_type": "string ({meal_type})",
  "estimated_cook_time_mins": integer,
  "ingredients_used": ["string (ingredient 1)", "string (ingredient 2)"],
  "missing_ingredients": ["string (ingredient needed but not in inventory)"],
  "instructions": [
    "Step 1...",
    "Step 2..."
  ],
  "waste_reduction_notes": "string explaining how this recipe reduces waste"
}}

Respond ONLY with raw JSON. Do not include markdown ticks, explanation text, or preamble.
"""
    return prompt


def call_gemini_api(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout_seconds: int = 30
) -> tuple[bool, dict | None, str]:
    """
    Calls the Google Gemini REST API generateContent endpoint with application/json configuration.
    Returns: (success: bool, raw_json_dict: dict | None, error_message: str)
    """
    if not api_key:
        msg = "GEMINI_API_KEY is not configured."
        logger.error(msg)
        return False, None, msg

    endpoint = f"{API_BASE_URL}/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.4
        }
    }

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            response_json = json.loads(body)
            return True, response_json, ""

    except urllib.error.HTTPError as err:
        err_details = err.read().decode("utf-8", errors="replace")
        msg = f"HTTP Error {err.code}: {err.reason} - {err_details}"
        logger.error(msg)
        return False, None, msg
    except urllib.error.URLError as err:
        msg = f"Network connection error: {err.reason}"
        logger.error(msg)
        return False, None, msg
    except json.JSONDecodeError as err:
        msg = f"Failed to parse API HTTP response as JSON: {err}"
        logger.error(msg)
        return False, None, msg
    except Exception as err:
        msg = f"Unexpected error during API call: {err}"
        logger.error(msg)
        return False, None, msg


def validate_recipe_schema(recipe_data: Any) -> tuple[bool, dict, str]:
    """
    Validates that the received dictionary contains all expected schema fields
    with valid types.
    Returns: (is_valid: bool, validated_dict: dict, error_message: str)
    """
    if not isinstance(recipe_data, dict):
        return False, {}, "Response is not a JSON object/dict."

    required_keys = {
        "recipe_name": str,
        "meal_type": str,
        "estimated_cook_time_mins": (int, float),
        "ingredients_used": list,
        "missing_ingredients": list,
        "instructions": list,
        "waste_reduction_notes": str
    }

    for key, expected_type in required_keys.items():
        if key not in recipe_data:
            return False, {}, f"Missing required schema field: '{key}'"
        if not isinstance(recipe_data[key], expected_type):
            return False, {}, f"Field '{key}' has invalid type {type(recipe_data[key])}, expected {expected_type}"

    # Clean and cast fields
    cleaned = {
        "recipe_name": str(recipe_data["recipe_name"]).strip(),
        "meal_type": str(recipe_data["meal_type"]).strip(),
        "estimated_cook_time_mins": int(recipe_data["estimated_cook_time_mins"]),
        "ingredients_used": [str(i).strip() for i in recipe_data["ingredients_used"] if str(i).strip()],
        "missing_ingredients": [str(i).strip() for i in recipe_data["missing_ingredients"] if str(i).strip()],
        "instructions": [str(s).strip() for s in recipe_data["instructions"] if str(s).strip()],
        "waste_reduction_notes": str(recipe_data["waste_reduction_notes"]).strip()
    }

    if not cleaned["recipe_name"]:
        return False, {}, "Recipe name cannot be empty."
    if not cleaned["ingredients_used"]:
        return False, {}, "Recipe must list at least one used ingredient."
    if not cleaned["instructions"]:
        return False, {}, "Recipe must provide step-by-step instructions."

    return True, cleaned, ""


def extract_recipe_json(gemini_response: dict) -> tuple[bool, dict, str]:
    """
    Extracts the structured JSON payload from Gemini generateContent response candidate.
    """
    try:
        candidates = gemini_response.get("candidates", [])
        if not candidates:
            return False, {}, "No candidates returned by Gemini API."

        content_parts = candidates[0].get("content", {}).get("parts", [])
        if not content_parts:
            return False, {}, "No content parts returned in candidate."

        text_content = content_parts[0].get("text", "").strip()
        if not text_content:
            return False, {}, "Candidate returned empty text."

        # Parse the JSON string
        parsed = json.loads(text_content)
        return validate_recipe_schema(parsed)

    except (KeyError, IndexError, json.JSONDecodeError) as err:
        msg = f"Failed to extract structured recipe JSON: {err}"
        logger.error(msg)
        return False, {}, msg


MODELS_CASCADE = ["gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"]


def request_recipe_from_ai(
    inventory: list[dict],
    meal_type: str,
    max_cook_time_mins: int,
    allergies: list[str],
    additional_notes: str = "",
    model: str = DEFAULT_MODEL
) -> tuple[bool, dict, str]:
    """
    Procedural facade orchestrating the AI request pipeline:
    1. Builds prompt
    2. Calls Gemini API with fallback cascade and graceful retry
    3. Validates structured JSON schema
    4. Handles errors gracefully without crashing
    Returns: (success: bool, recipe_dict: dict, error_or_status_message: str)
    """
    import time
    api_key = get_api_key()
    if not api_key:
        return False, {}, "Gemini API key is not configured. Please set GEMINI_API_KEY."

    prompt = build_recipe_prompt(
        inventory_items=inventory,
        meal_type=meal_type,
        max_cook_time_mins=max_cook_time_mins,
        allergies=allergies,
        additional_notes=additional_notes
    )

    models_to_try = [model] + [m for m in MODELS_CASCADE if m != model]
    last_error = ""

    for target_model in models_to_try:
        for attempt in range(2):  # Try twice per model
            success, raw_resp, err = call_gemini_api(prompt=prompt, api_key=api_key, model=target_model)
            if success and raw_resp is not None:
                valid, validated_recipe, val_err = extract_recipe_json(raw_resp)
                if valid:
                    return True, validated_recipe, "Recipe generated and schema validated successfully."
                last_error = f"Schema validation error on {target_model}: {val_err}"
            else:
                last_error = f"API error on {target_model}: {err}"
                # If rate-limited or busy, brief backoff
                if "503" in err or "429" in err:
                    time.sleep(1.5)

    logger.error("All AI model attempts exhausted. Last error: %s", last_error)
    return False, {}, f"AI API service temporarily unavailable: {last_error}"
