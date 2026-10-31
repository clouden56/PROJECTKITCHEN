"""
IO Manager - user input and output.

Turns raw web form fields into validated, typed domain objects (never letting raw strings reach the other
layers) and formats domain objects for display. Invalid input is reported field by field so the page can
be shown again with the user's values and an explanation, instead of failing.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Generic, Iterable, Mapping, TypeVar

from src.data_manager import AllFilters, IngredientFilter, MealTypeFilter, OutcomeFilter, RecordFilter
from src.models import DATE_FORMAT, Ingredient, Outcome, RecipeRequest

T = TypeVar("T")


class FieldError(ValueError):
    """A single form field holds an invalid value; the message is shown next to the field."""


class FormField(ABC):
    """One input field. clean() handles the shared required/blank logic; subclasses convert the text."""

    def __init__(self, name: str, label: str, required: bool = True) -> None:
        self._name = name
        self._label = label
        self._required = required

    @property
    def name(self) -> str:
        return self._name

    @property
    def label(self) -> str:
        return self._label

    def clean(self, raw: Any) -> Any:
        text = "" if raw is None else str(raw).strip()
        if not text:
            if self._required:
                raise FieldError(f"{self._label} is required.")
            return self.empty_value()
        return self._convert(text)

    def empty_value(self) -> Any:
        return None

    @abstractmethod
    def _convert(self, text: str) -> Any:
        """Converts non-blank text to the field's type, raising FieldError if it is invalid."""


class TextField(FormField):
    def __init__(self, name: str, label: str, max_length: int, required: bool = True) -> None:
        super().__init__(name, label, required)
        self._max_length = max_length

    def empty_value(self) -> str:
        return ""

    def _convert(self, text: str) -> str:
        if len(text) > self._max_length:
            raise FieldError(f"{self._label} must be at most {self._max_length} characters.")
        return text


class NumberField(FormField):
    """A positive, finite number; optionally a whole number with an upper limit."""

    def __init__(self, name: str, label: str, whole: bool = False, maximum: float | None = None) -> None:
        super().__init__(name, label)
        self._whole = whole
        self._maximum = maximum

    def _convert(self, text: str) -> int | float:
        try:
            value: int | float = int(text) if self._whole else float(text)
        except ValueError:
            kind = "a whole number" if self._whole else "a number"
            raise FieldError(f"{self._label} must be {kind}.") from None
        if not math.isfinite(value) or value <= 0:
            raise FieldError(f"{self._label} must be greater than 0.")
        if self._maximum is not None and value > self._maximum:
            raise FieldError(f"{self._label} must be at most {self._maximum:g}.")
        return value


class DateField(FormField):
    def _convert(self, text: str) -> date:
        try:
            return datetime.strptime(text, DATE_FORMAT).date()
        except ValueError:
            raise FieldError(f"{self._label} must be a real date in YYYY-MM-DD format.") from None


class ChoiceField(FormField):
    def __init__(self, name: str, label: str, choices: Iterable[str], required: bool = True) -> None:
        super().__init__(name, label, required)
        self._choices = tuple(choices)

    @property
    def choices(self) -> tuple[str, ...]:
        return self._choices

    def _convert(self, text: str) -> str:
        match = next((c for c in self._choices if c.lower() == text.lower()), None)
        if match is None:
            raise FieldError(f"{self._label} must be one of: {', '.join(self._choices)}.")
        return match


class ListField(FormField):
    """Comma-separated values, e.g. 'peanuts, dairy'. Blank entries are dropped."""

    def __init__(self, name: str, label: str, max_items: int = 10) -> None:
        super().__init__(name, label, required=False)
        self._max_items = max_items

    def empty_value(self) -> list[str]:
        return []

    def _convert(self, text: str) -> list[str]:
        items = list(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))
        if len(items) > self._max_items:
            raise FieldError(f"{self._label} can list at most {self._max_items} items.")
        if any(len(item) > 40 for item in items):
            raise FieldError(f"Each entry in {self._label} must be at most 40 characters.")
        return items


class Form:
    """A set of fields validated together. Composes its fields: they are created for and owned by the form."""

    def __init__(self, fields: Iterable[FormField]) -> None:
        self._fields = tuple(fields)

    @property
    def fields(self) -> tuple[FormField, ...]:
        return self._fields

    def clean(self, data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        values: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for field in self._fields:
            try:
                values[field.name] = field.clean(data.get(field.name))
            except FieldError as err:
                errors[field.name] = str(err)
        return values, errors


class FormResult(Generic[T]):
    """Either a validated object or the per-field errors, plus the submitted text to redisplay."""

    def __init__(self, value: T | None, errors: Mapping[str, str], submitted: Mapping[str, str]) -> None:
        self._value = value
        self._errors = dict(errors)
        self._submitted = dict(submitted)

    @property
    def ok(self) -> bool:
        return self._value is not None and not self._errors

    @property
    def value(self) -> T | None:
        return self._value

    @property
    def errors(self) -> dict[str, str]:
        return self._errors

    @property
    def submitted(self) -> dict[str, str]:
        return self._submitted


class IOManager:
    """Validates everything the user submits and prepares domain objects for display."""

    OUTCOME_STYLES = {Outcome.ACCEPTED: "accepted", Outcome.FLAGGED: "flagged", Outcome.REJECTED: "rejected"}
    EXPIRY_LABELS = {"expired": "Expired", "today": "Expires today", "unknown": "No date"}

    def __init__(self) -> None:
        self._ingredient_form = Form([
            TextField("name", "Ingredient name", max_length=60),
            NumberField("quantity", "Quantity", maximum=100000),
            TextField("unit", "Unit", max_length=20),
            ChoiceField("location", "Storage location", Ingredient.LOCATIONS),
            DateField("expiry_date", "Expiry date"),
        ])
        self._request_form = Form([
            ChoiceField("meal_type", "Meal type", RecipeRequest.MEAL_TYPES),
            NumberField("max_cook_time_mins", "Maximum cooking time", whole=True, maximum=RecipeRequest.MAX_COOK_TIME),
            ListField("allergies", "Allergies"),
            ListField("mandatory_ingredients", "Must-include ingredients"),
            TextField("notes", "Cooking style", max_length=200, required=False),
        ])

    @property
    def meal_types(self) -> tuple[str, ...]:
        return RecipeRequest.MEAL_TYPES

    @property
    def locations(self) -> tuple[str, ...]:
        return Ingredient.LOCATIONS

    @property
    def outcomes(self) -> tuple[str, ...]:
        return tuple(o.value for o in Outcome)

    def parse_ingredient(self, form: Mapping[str, Any]) -> FormResult[Ingredient]:
        values, errors = self._ingredient_form.clean(form)
        ingredient = None
        if not errors:
            try:
                ingredient = Ingredient(values["name"], values["quantity"], values["unit"],
                                        values["expiry_date"], values["location"])
            except ValueError as err:
                errors["name"] = str(err)
        return FormResult(ingredient, errors, self._submitted(form, self._ingredient_form))

    def parse_recipe_request(self, form: Mapping[str, Any]) -> FormResult[RecipeRequest]:
        values, errors = self._request_form.clean(form)
        request = None
        if not errors:
            try:
                request = RecipeRequest(**values)
            except ValueError as err:
                errors["meal_type"] = str(err)
        return FormResult(request, errors, self._submitted(form, self._request_form))

    def parse_history_filter(self, args: Mapping[str, Any]) -> tuple[RecordFilter, dict[str, str]]:
        """Builds the history search from the query string. Unknown values are ignored, not errors."""
        selected = {key: str(args.get(key, "")).strip() for key in ("meal_type", "ingredient", "outcome")}
        filters: list[RecordFilter] = []
        meal = next((m for m in self.meal_types if m.lower() == selected["meal_type"].lower()), None)
        if meal:
            filters.append(MealTypeFilter(meal))
        else:
            selected["meal_type"] = ""
        if selected["ingredient"]:
            selected["ingredient"] = selected["ingredient"][:40]
            filters.append(IngredientFilter(selected["ingredient"]))
        outcome = next((o for o in Outcome if o.value == selected["outcome"].upper()), None)
        if outcome:
            filters.append(OutcomeFilter(outcome))
            selected["outcome"] = outcome.value
        else:
            selected["outcome"] = ""
        return AllFilters(filters), selected

    def expiry_badge(self, ingredient: Ingredient, today: date) -> tuple[str, str]:
        """(label, style) for an ingredient's freshness, e.g. ('2 days left', 'soon')."""
        status = ingredient.expiry_status(today)
        if status in self.EXPIRY_LABELS:
            return self.EXPIRY_LABELS[status], status
        days = ingredient.days_until_expiry(today)
        return f"{days} day{'s' if days != 1 else ''} left", status

    def outcome_style(self, outcome: Outcome) -> str:
        return self.OUTCOME_STYLES.get(outcome, "flagged")

    @staticmethod
    def format_quantity(quantity: float | None, unit: str) -> str:
        if quantity is None:
            return unit
        return f"{quantity:g} {unit}".strip()

    @staticmethod
    def _submitted(form: Mapping[str, Any], spec: Form) -> dict[str, str]:
        return {field.name: str(form.get(field.name, "") or "") for field in spec.fields}
