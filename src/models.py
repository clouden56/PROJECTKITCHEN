"""
Domain model for the Fridge Recipe Tracker.

These classes are the records that flow through the four managers:
an Inventory of Ingredients and a RecipeRequest form a RecipeJob, the AI turns the job into a Recipe,
the logic layer produces an Evaluation, and the data layer stores the result as a HistoryRecord.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, Iterator

DATE_FORMAT = "%Y-%m-%d"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
NO_EXPIRY_DAYS = 999


class Outcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class Ingredient:
    """One item in the fridge or pantry. Validates itself so an invalid item can never be stored."""

    LOCATIONS = ("Fridge", "Pantry")

    def __init__(
        self,
        name: str,
        quantity: float,
        unit: str,
        expiry_date: date | None,
        location: str = "Fridge",
        ingredient_id: str | None = None,
    ) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Ingredient name is required.")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            raise ValueError("Quantity must be a number.")
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("Quantity must be a finite number greater than 0.")
        if location not in self.LOCATIONS:
            raise ValueError(f"Location must be one of: {', '.join(self.LOCATIONS)}.")
        self._id = ingredient_id
        self._name = name
        self._quantity = float(quantity)
        self._unit = (unit or "").strip()
        self._expiry_date = expiry_date
        self._location = location

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def quantity(self) -> float:
        return self._quantity

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def expiry_date(self) -> date | None:
        return self._expiry_date

    @property
    def location(self) -> str:
        return self._location

    def assign_id(self, ingredient_id: str) -> None:
        if self._id is None:
            self._id = ingredient_id

    def has_name(self, name: str) -> bool:
        return self._name.lower() == (name or "").strip().lower()

    def days_until_expiry(self, today: date) -> int:
        """Positive = days left, 0 = expires today, negative = already expired."""
        if self._expiry_date is None:
            return NO_EXPIRY_DAYS
        return (self._expiry_date - today).days

    def expiry_status(self, today: date, soon_days: int = 3) -> str:
        days = self.days_until_expiry(today)
        if self._expiry_date is None:
            return "unknown"
        if days < 0:
            return "expired"
        if days == 0:
            return "today"
        if days <= soon_days:
            return "soon"
        return "ok"

    def update_from(self, other: Ingredient) -> None:
        """Restocking an existing item replaces its quantity, unit, expiry and location."""
        self._quantity = other.quantity
        self._unit = other.unit
        self._expiry_date = other.expiry_date
        self._location = other.location

    def to_dict(self) -> dict[str, Any]:
        quantity: float | int = int(self._quantity) if self._quantity.is_integer() else self._quantity
        return {
            "id": self._id,
            "name": self._name,
            "quantity": quantity,
            "unit": self._unit,
            "location": self._location,
            "expiry_date": self._expiry_date.strftime(DATE_FORMAT) if self._expiry_date else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Ingredient:
        return cls(
            name=data["name"],
            quantity=data["quantity"],
            unit=data.get("unit", ""),
            expiry_date=cls.parse_date(data.get("expiry_date")),
            location=data.get("location") or "Fridge",
            ingredient_id=data.get("id"),
        )

    @staticmethod
    def parse_date(value: Any) -> date | None:
        """Lenient parse for stored data: a missing or malformed date means 'no known expiry'."""
        try:
            return datetime.strptime(str(value).strip(), DATE_FORMAT).date()
        except (TypeError, ValueError):
            return None

    def __repr__(self) -> str:
        return f"Ingredient({self._name!r}, {self._quantity:g} {self._unit}, expires={self._expiry_date})"


class Inventory:
    """
    The household's stock. Aggregates Ingredient objects: ingredients are created outside the
    inventory and keep existing after removal (e.g. to show what was removed).
    """

    def __init__(self, ingredients: Iterable[Ingredient] = ()) -> None:
        self._items: list[Ingredient] = []
        for ingredient in ingredients:
            self.add_or_update(ingredient)

    def __iter__(self) -> Iterator[Ingredient]:
        return iter(list(self._items))

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> tuple[Ingredient, ...]:
        return tuple(self._items)

    def find(self, name: str) -> Ingredient | None:
        return next((item for item in self._items if item.has_name(name)), None)

    def add_or_update(self, ingredient: Ingredient) -> Ingredient:
        """Adds a new item, or restocks the existing item with the same name. Returns the stored item."""
        existing = self.find(ingredient.name)
        if existing is not None:
            existing.update_from(ingredient)
            return existing
        ingredient.assign_id(self._next_id())
        self._items.append(ingredient)
        return ingredient

    def remove(self, name: str) -> Ingredient | None:
        item = self.find(name)
        if item is not None:
            self._items.remove(item)
        return item

    def expiring_within(self, days: int, today: date) -> list[Ingredient]:
        """Items with a known expiry date within `days`, soonest first (includes expired items)."""
        urgent = [i for i in self._items if i.expiry_date is not None and i.days_until_expiry(today) <= days]
        return sorted(urgent, key=lambda i: i.days_until_expiry(today))

    def _next_id(self) -> str:
        numbers = []
        for item in self._items:
            suffix = (item.id or "").rpartition("-")[2]
            if suffix.isdigit():
                numbers.append(int(suffix))
        return f"ing-{max(numbers, default=0) + 1:03d}"


class RecipeRequest:
    """The user's validated constraints for one recipe suggestion."""

    MEAL_TYPES = ("Breakfast", "Lunch", "Dinner", "Snack")
    MAX_COOK_TIME = 600

    def __init__(
        self,
        meal_type: str,
        max_cook_time_mins: int,
        allergies: Iterable[str] = (),
        mandatory_ingredients: Iterable[str] = (),
        notes: str = "",
    ) -> None:
        if meal_type not in self.MEAL_TYPES:
            raise ValueError(f"Meal type must be one of: {', '.join(self.MEAL_TYPES)}.")
        if isinstance(max_cook_time_mins, bool) or not isinstance(max_cook_time_mins, int):
            raise ValueError("Maximum cooking time must be a whole number of minutes.")
        if not 1 <= max_cook_time_mins <= self.MAX_COOK_TIME:
            raise ValueError(f"Maximum cooking time must be between 1 and {self.MAX_COOK_TIME} minutes.")
        self._meal_type = meal_type
        self._max_cook_time_mins = max_cook_time_mins
        self._allergies = self._clean(allergies)
        self._mandatory_ingredients = self._clean(mandatory_ingredients)
        self._notes = (notes or "").strip()

    @staticmethod
    def _clean(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v.strip() for v in values if v and v.strip()))

    @property
    def meal_type(self) -> str:
        return self._meal_type

    @property
    def max_cook_time_mins(self) -> int:
        return self._max_cook_time_mins

    @property
    def allergies(self) -> tuple[str, ...]:
        return self._allergies

    @property
    def mandatory_ingredients(self) -> tuple[str, ...]:
        return self._mandatory_ingredients

    @property
    def notes(self) -> str:
        return self._notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "meal_type": self._meal_type,
            "max_cook_time_mins": self._max_cook_time_mins,
            "allergies": list(self._allergies),
            "mandatory_ingredients": list(self._mandatory_ingredients),
            "notes": self._notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecipeRequest:
        return cls(
            meal_type=data["meal_type"],
            max_cook_time_mins=data["max_cook_time_mins"],
            allergies=data.get("allergies", []),
            mandatory_ingredients=data.get("mandatory_ingredients", []),
            notes=data.get("notes", ""),
        )


class RecipeJob:
    """
    One unit of work for the pipeline: a request plus the inventory it should be cooked from.
    Associated with (not owning) the Inventory, which outlives the job.
    """

    def __init__(self, request: RecipeRequest, inventory: Inventory) -> None:
        self._request = request
        self._inventory = inventory

    @property
    def request(self) -> RecipeRequest:
        return self._request

    @property
    def inventory(self) -> Inventory:
        return self._inventory


class RecipeStep:
    """A numbered cooking instruction. Only exists as part of its Recipe."""

    def __init__(self, number: int, text: str) -> None:
        self._number = number
        self._text = text

    @property
    def number(self) -> int:
        return self._number

    @property
    def text(self) -> str:
        return self._text


class Recipe:
    """
    A validated AI-generated recipe. Composes its RecipeSteps: the recipe creates them from the raw
    instruction text and they are never shared with, or outlive, another recipe.
    """

    def __init__(
        self,
        name: str,
        meal_type: str,
        cook_time_mins: int,
        ingredients_used: Iterable[str],
        missing_ingredients: Iterable[str],
        instructions: Iterable[str],
        required_tools: Iterable[str] = (),
        waste_reduction_notes: str = "",
    ) -> None:
        self._name = name
        self._meal_type = meal_type
        self._cook_time_mins = cook_time_mins
        self._ingredients_used = tuple(ingredients_used)
        self._missing_ingredients = tuple(missing_ingredients)
        self._steps = tuple(RecipeStep(n, text) for n, text in enumerate(instructions, 1))
        self._required_tools = tuple(required_tools)
        self._waste_reduction_notes = waste_reduction_notes

    @property
    def name(self) -> str:
        return self._name

    @property
    def meal_type(self) -> str:
        return self._meal_type

    @property
    def cook_time_mins(self) -> int:
        return self._cook_time_mins

    @property
    def ingredients_used(self) -> tuple[str, ...]:
        return self._ingredients_used

    @property
    def missing_ingredients(self) -> tuple[str, ...]:
        return self._missing_ingredients

    @property
    def steps(self) -> tuple[RecipeStep, ...]:
        return self._steps

    @property
    def required_tools(self) -> tuple[str, ...]:
        return self._required_tools

    @property
    def waste_reduction_notes(self) -> str:
        return self._waste_reduction_notes

    def all_ingredients(self) -> tuple[str, ...]:
        return self._ingredients_used + self._missing_ingredients

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_name": self._name,
            "meal_type": self._meal_type,
            "estimated_cook_time_mins": self._cook_time_mins,
            "required_tools": list(self._required_tools),
            "ingredients_used": list(self._ingredients_used),
            "missing_ingredients": list(self._missing_ingredients),
            "instructions": [step.text for step in self._steps],
            "waste_reduction_notes": self._waste_reduction_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recipe:
        return cls(
            name=data["recipe_name"],
            meal_type=data.get("meal_type", ""),
            cook_time_mins=int(data.get("estimated_cook_time_mins", 0)),
            ingredients_used=data.get("ingredients_used", []),
            missing_ingredients=data.get("missing_ingredients", []),
            instructions=data.get("instructions", []),
            required_tools=data.get("required_tools", []),
            waste_reduction_notes=data.get("waste_reduction_notes", ""),
        )


class RescuedItem:
    """An inventory item that a recipe uses before it spoils."""

    def __init__(self, name: str, days_until_expiry: int, quantity: float | None, unit: str) -> None:
        self._name = name
        self._days_until_expiry = days_until_expiry
        self._quantity = quantity
        self._unit = unit

    @property
    def name(self) -> str:
        return self._name

    @property
    def days_until_expiry(self) -> int:
        return self._days_until_expiry

    @property
    def quantity(self) -> float | None:
        return self._quantity

    @property
    def unit(self) -> str:
        return self._unit

    def to_dict(self) -> dict[str, Any]:
        return {"name": self._name, "days_until_expiry": self._days_until_expiry,
                "quantity": self._quantity, "unit": self._unit}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RescuedItem:
        return cls(str(data.get("name", "")), int(data.get("days_until_expiry", NO_EXPIRY_DAYS)),
                   data.get("quantity"), str(data.get("unit", "")))


class RuleResult:
    """The result of checking one business rule; the list of these explains a verdict."""

    def __init__(self, rule_name: str, passed: bool, outcome: Outcome | None = None,
                 status_code: str = "", message: str = "") -> None:
        self._rule_name = rule_name
        self._passed = passed
        self._outcome = outcome
        self._status_code = status_code
        self._message = message

    @property
    def rule_name(self) -> str:
        return self._rule_name

    @property
    def passed(self) -> bool:
        return self._passed

    @property
    def outcome(self) -> Outcome | None:
        return self._outcome

    @property
    def status_code(self) -> str:
        return self._status_code

    @property
    def message(self) -> str:
        return self._message

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self._rule_name, "passed": self._passed,
                "outcome": self._outcome.value if self._outcome else None,
                "status_code": self._status_code, "message": self._message}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleResult:
        outcome = data.get("outcome")
        return cls(str(data.get("rule", "")), bool(data.get("passed")),
                   Outcome(outcome) if outcome else None,
                   str(data.get("status_code", "")), str(data.get("message", "")))


class Evaluation:
    """The logic layer's verdict on one recipe, with the evidence behind it."""

    def __init__(
        self,
        outcome: Outcome,
        status_code: str,
        status_message: str,
        match_ratio: float,
        matched_ingredients: Iterable[str],
        missing_ingredients: Iterable[str],
        missing_mandatory: Iterable[str],
        expiry_priority_score: float,
        rescued_items: Iterable[RescuedItem],
        waste_diverted_grams: int,
        allergen_safe: bool,
        is_within_time: bool,
        rule_results: Iterable[RuleResult] = (),
    ) -> None:
        self._outcome = Outcome(outcome)
        self._status_code = status_code
        self._status_message = status_message
        self._match_ratio = match_ratio
        self._matched_ingredients = tuple(matched_ingredients)
        self._missing_ingredients = tuple(missing_ingredients)
        self._missing_mandatory = tuple(missing_mandatory)
        self._expiry_priority_score = expiry_priority_score
        self._rescued_items = tuple(rescued_items)
        self._waste_diverted_grams = waste_diverted_grams
        self._allergen_safe = allergen_safe
        self._is_within_time = is_within_time
        self._rule_results = tuple(rule_results)

    @property
    def outcome(self) -> Outcome:
        return self._outcome

    @property
    def status_code(self) -> str:
        return self._status_code

    @property
    def status_message(self) -> str:
        return self._status_message

    @property
    def match_ratio(self) -> float:
        return self._match_ratio

    @property
    def match_percentage(self) -> int:
        return int(round(self._match_ratio * 100))

    @property
    def matched_ingredients(self) -> tuple[str, ...]:
        return self._matched_ingredients

    @property
    def missing_ingredients(self) -> tuple[str, ...]:
        return self._missing_ingredients

    @property
    def missing_mandatory(self) -> tuple[str, ...]:
        return self._missing_mandatory

    @property
    def mandatory_met(self) -> bool:
        return not self._missing_mandatory

    @property
    def expiry_priority_score(self) -> float:
        return self._expiry_priority_score

    @property
    def rescued_items(self) -> tuple[RescuedItem, ...]:
        return self._rescued_items

    @property
    def waste_diverted_grams(self) -> int:
        return self._waste_diverted_grams

    @property
    def allergen_safe(self) -> bool:
        return self._allergen_safe

    @property
    def is_within_time(self) -> bool:
        return self._is_within_time

    @property
    def rule_results(self) -> tuple[RuleResult, ...]:
        return self._rule_results

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self._outcome.value,
            "status_code": self._status_code,
            "status_message": self._status_message,
            "match_ratio": self._match_ratio,
            "match_percentage": self.match_percentage,
            "matched_ingredients": list(self._matched_ingredients),
            "missing_ingredients": list(self._missing_ingredients),
            "mandatory_met": self.mandatory_met,
            "missing_mandatory": list(self._missing_mandatory),
            "expiry_priority_score": self._expiry_priority_score,
            "rescued_items": [item.to_dict() for item in self._rescued_items],
            "waste_diverted_grams": self._waste_diverted_grams,
            "allergen_safe": self._allergen_safe,
            "is_within_time": self._is_within_time,
            "rule_results": [result.to_dict() for result in self._rule_results],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Evaluation:
        return cls(
            outcome=Outcome(data["outcome"]),
            status_code=data.get("status_code", ""),
            status_message=data.get("status_message", ""),
            match_ratio=float(data.get("match_ratio", 0.0)),
            matched_ingredients=data.get("matched_ingredients", []),
            missing_ingredients=data.get("missing_ingredients", []),
            missing_mandatory=data.get("missing_mandatory", []),
            expiry_priority_score=float(data.get("expiry_priority_score", 0.0)),
            rescued_items=[RescuedItem.from_dict(r) for r in data.get("rescued_items", []) if isinstance(r, dict)],
            waste_diverted_grams=int(data.get("waste_diverted_grams", 0)),
            allergen_safe=bool(data.get("allergen_safe", True)),
            is_within_time=bool(data.get("is_within_time", True)),
            rule_results=[RuleResult.from_dict(r) for r in data.get("rule_results", []) if isinstance(r, dict)],
        )


class HistoryRecord:
    """
    A saved recipe suggestion. Composes its Recipe and Evaluation (a record's recipe and verdict belong
    to that record alone) and keeps the request that produced them so the verdict can be re-checked later.
    """

    def __init__(
        self,
        recipe: Recipe,
        evaluation: Evaluation,
        request: RecipeRequest | None = None,
        created_at: datetime | None = None,
        record_id: str | None = None,
    ) -> None:
        self._recipe = recipe
        self._evaluation = evaluation
        self._request = request
        self._created_at = created_at or datetime.now().replace(microsecond=0)
        self._id = record_id or uuid.uuid4().hex[:10]

    @property
    def id(self) -> str:
        return self._id

    @property
    def recipe(self) -> Recipe:
        return self._recipe

    @property
    def evaluation(self) -> Evaluation:
        return self._evaluation

    @property
    def request(self) -> RecipeRequest | None:
        return self._request

    @property
    def created_at(self) -> datetime:
        return self._created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self._id,
            "created_at": self._created_at.strftime(TIMESTAMP_FORMAT),
            "request": self._request.to_dict() if self._request else None,
            "recipe": self._recipe.to_dict(),
            "evaluation": self._evaluation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryRecord:
        created_raw = str(data.get("created_at", ""))
        try:
            created_at = datetime.strptime(created_raw, TIMESTAMP_FORMAT)
        except ValueError:
            created_at = None
        request_data = data.get("request")
        recipe = Recipe.from_dict(data["recipe"])
        return cls(
            recipe=recipe,
            evaluation=Evaluation.from_dict(data["evaluation"]),
            request=RecipeRequest.from_dict(request_data) if isinstance(request_data, dict) else None,
            created_at=created_at or datetime(1970, 1, 1),
            record_id=data.get("id") or cls.legacy_id(created_raw, recipe.name),
        )

    @staticmethod
    def legacy_id(created_at: str, recipe_name: str) -> str:
        """Stable id for Phase 1 records saved before ids existed, so their links never change."""
        return hashlib.sha1(f"{created_at}|{recipe_name}".encode("utf-8")).hexdigest()[:10]
