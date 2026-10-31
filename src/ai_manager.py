"""
AI Manager - AI processing layer.

Every recipe request passes through here: build a prompt, call the AI API, parse the reply and validate
it against the recipe schema. Contains no domain rules; the logic layer judges the validated recipe.
Connection failures, timeouts, malformed replies and schema violations are retried or reported as an
AIProcessingError, never as a crash.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Generic, Sequence, TypeVar

from src.models import Recipe, RecipeJob

logger = logging.getLogger(__name__)

R = TypeVar("R")
J = TypeVar("J")


class AIServiceError(Exception):
    """Base class for every AI failure."""


class AIConnectionError(AIServiceError):
    """Transient failure (network down, timeout, rate limit, server error): worth retrying."""


class AIAuthenticationError(AIServiceError):
    """Missing, invalid or revoked API key: no retry or other model can succeed."""


class AIRequestRejectedError(AIServiceError):
    """The model rejected the request or no longer exists: try the next model instead."""


class AIResponseError(AIServiceError):
    """The reply was not usable JSON, or broke the expected schema."""


class AIProcessingError(AIServiceError):
    """Raised by AIManager.process() when no usable result could be obtained."""


class AIClient(ABC):
    """Interface to a text-generation service. Implementations raise the AIServiceError subclasses above."""

    @abstractmethod
    def generate(self, prompt: str, model: str) -> str:
        """Returns the model's raw text reply to the prompt."""


class GeminiClient(AIClient):
    """Google Gemini generateContent REST client using only the standard library."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout_seconds: int = 30,
                 temperature: float = 0.0) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature

    def generate(self, prompt: str, model: str) -> str:
        if not self._api_key:
            raise AIAuthenticationError("Gemini API key is not configured. Set GEMINI_API_KEY.")
        body = self._post(f"{self._base_url}/{model}:generateContent", {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": self._temperature},
        })
        return self._extract_text(body)

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            with err:
                details = err.read().decode("utf-8", errors="replace")
            raise self._error_for_status(err.code, f"HTTP {err.code} {err.reason}: {details[:300]}") from err
        except urllib.error.URLError as err:
            raise AIConnectionError(f"Network connection error: {err.reason}") from err
        except TimeoutError as err:
            raise AIConnectionError(f"No response within {self._timeout_seconds} seconds.") from err
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise AIResponseError(f"API reply was not JSON: {err}") from err
        if not isinstance(body, dict):
            raise AIResponseError("API reply was JSON but not an object.")
        return body

    @staticmethod
    def _error_for_status(status: int, message: str) -> AIServiceError:
        if status in (401, 403) or "API_KEY_INVALID" in message:
            return AIAuthenticationError(message)
        if status in (400, 404):
            return AIRequestRejectedError(message)
        return AIConnectionError(message)

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        try:
            candidates = body.get("candidates") or []
            if not candidates:
                reason = (body.get("promptFeedback") or {}).get("blockReason", "no candidates")
                raise AIResponseError(f"Gemini returned no candidates ({reason}).")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = parts[0].get("text", "") if parts else ""
        except (AttributeError, IndexError, TypeError) as err:
            raise AIResponseError(f"Unexpected Gemini response shape: {err}") from err
        if not isinstance(text, str) or not text.strip():
            raise AIResponseError("Gemini returned an empty reply.")
        return text


class AIManager(ABC, Generic[J, R]):
    """
    Template for turning one record into a validated result through an AI service.
    process() fixes the order (build_prompt -> call_api -> parse_response -> validate_response) and the
    retry policy; subclasses supply the record-specific prompt and schema.
    """

    def __init__(self, client: AIClient, models: Sequence[str], attempts_per_model: int = 2,
                 retry_delay_seconds: float = 1.5, sleep: Callable[[float], None] = time.sleep) -> None:
        if not models:
            raise ValueError("At least one model is required.")
        self._client = client
        self._models = tuple(models)
        self._attempts_per_model = max(1, attempts_per_model)
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    @property
    def models(self) -> tuple[str, ...]:
        return self._models

    def process(self, record: J) -> R:
        prompt = self.build_prompt(record)
        last_error: AIServiceError | None = None
        for model in self._models:
            for attempt in range(1, self._attempts_per_model + 1):
                try:
                    return self.validate_response(self.parse_response(self.call_api(prompt, model)))
                except AIAuthenticationError as err:
                    logger.error("AI authentication failed: %s", err)
                    raise AIProcessingError(f"AI request rejected - check your GEMINI_API_KEY. ({err})") from err
                except AIRequestRejectedError as err:
                    logger.warning("Model %s rejected the request: %s", model, err)
                    last_error = err
                    break
                except AIConnectionError as err:
                    logger.warning("Model %s attempt %d failed: %s", model, attempt, err)
                    last_error = err
                    if attempt < self._attempts_per_model:
                        self._sleep(self._retry_delay_seconds)
                except AIResponseError as err:
                    logger.warning("Model %s gave an unusable reply: %s", model, err)
                    last_error = err
        raise AIProcessingError(f"The AI service is unavailable right now. Last error: {last_error}")

    @abstractmethod
    def build_prompt(self, record: J) -> str:
        """Turns the record into a prompt that demands JSON output."""

    def call_api(self, prompt: str, model: str) -> str:
        return self._client.generate(prompt, model)

    def parse_response(self, raw: str) -> Any:
        """Extracts the JSON value from the reply text, tolerating a surrounding markdown code fence."""
        text = raw.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise AIResponseError(f"Reply is not valid JSON: {err}") from err

    @abstractmethod
    def validate_response(self, data: Any) -> R:
        """Checks the parsed JSON against the schema and builds the result; raises AIResponseError."""


class RecipeAIManager(AIManager[RecipeJob, Recipe]):
    """Asks the AI for one recipe that uses up the ingredients closest to expiry."""

    REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
        "recipe_name": str,
        "meal_type": str,
        "estimated_cook_time_mins": (int, float),
        "required_tools": list,
        "ingredients_used": list,
        "missing_ingredients": list,
        "instructions": list,
        "waste_reduction_notes": str,
    }
    MAX_COOK_TIME_MINS = 24 * 60

    def build_prompt(self, record: RecipeJob) -> str:
        request = record.request
        lines = []
        for item in record.inventory:
            expiry = item.expiry_date.isoformat() if item.expiry_date else "unknown"
            lines.append(f"- {item.name} ({item.quantity:g} {item.unit}, {item.location}, expires {expiry})")
        inventory_text = "\n".join(lines) or "No ingredients recorded."
        allergies = ", ".join(request.allergies) or "None"
        must_include = ", ".join(request.mandatory_ingredients) or "None (chef's choice from the inventory)"
        notes = request.notes or "Prioritise the ingredients that expire soonest."
        return f"""You are a professional chef and food-waste reduction assistant.
The user has these ingredients in their fridge and pantry:
{inventory_text}

Constraints:
- Meal type: {request.meal_type}
- Maximum cooking time: {request.max_cook_time_mins} minutes
- Allergies / ingredients that must NOT appear: {allergies}
- Ingredients that MUST be included: {must_include}
- Cooking style / notes: {notes}

Suggest one recipe that includes the must-have ingredients, uses as many available ingredients as possible
(especially those expiring soonest) and minimises food waste.

Respond ONLY with a JSON object matching this schema, with no markdown and no extra text:
{{
  "recipe_name": "string",
  "meal_type": "{request.meal_type}",
  "estimated_cook_time_mins": integer,
  "required_tools": ["string"],
  "ingredients_used": ["ingredient from the list above, with amount"],
  "missing_ingredients": ["ingredient the user would need to buy"],
  "instructions": ["Step 1 ...", "Step 2 ..."],
  "waste_reduction_notes": "string explaining how this recipe reduces waste"
}}"""

    def validate_response(self, data: Any) -> Recipe:
        if not isinstance(data, dict):
            raise AIResponseError("Reply is not a JSON object.")
        for key, expected in self.REQUIRED_FIELDS.items():
            if key not in data:
                raise AIResponseError(f"Missing required field '{key}'.")
            value = data[key]
            if isinstance(value, bool) or not isinstance(value, expected):
                raise AIResponseError(f"Field '{key}' has the wrong type ({type(value).__name__}).")
        cook_time = data["estimated_cook_time_mins"]
        if not math.isfinite(cook_time) or not 0 <= cook_time <= self.MAX_COOK_TIME_MINS:
            raise AIResponseError(f"Cook time {cook_time} is outside 0-{self.MAX_COOK_TIME_MINS} minutes.")

        name = str(data["recipe_name"]).strip()
        used = self._clean_list(data["ingredients_used"])
        steps = self._clean_list(data["instructions"])
        if not name:
            raise AIResponseError("Recipe name is empty.")
        if not used:
            raise AIResponseError("Recipe lists no ingredients.")
        if not steps:
            raise AIResponseError("Recipe has no instructions.")
        return Recipe(
            name=name,
            meal_type=str(data["meal_type"]).strip(),
            cook_time_mins=int(cook_time),
            ingredients_used=used,
            missing_ingredients=self._clean_list(data["missing_ingredients"]),
            instructions=steps,
            required_tools=self._clean_list(data["required_tools"]) or ["Standard kitchen utensils"],
            waste_reduction_notes=str(data["waste_reduction_notes"]).strip(),
        )

    @staticmethod
    def _clean_list(values: list[Any]) -> list[str]:
        return [str(v).strip() for v in values if str(v).strip()]
