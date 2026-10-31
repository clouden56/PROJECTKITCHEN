"""
Application service: runs each use case through the four managers in the required order
(input -> AI -> logic -> data) so the user interface never talks to a manager's internals.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Callable

from src.ai_manager import AIManager
from src.data_manager import AllFilters, DataManager, RecordFilter
from src.logic_manager import LogicManager
from src.models import (
    Evaluation, HistoryRecord, Ingredient, Inventory, Outcome, Recipe, RecipeJob, RecipeRequest, RuleResult,
)

logger = logging.getLogger(__name__)


class KitchenError(Exception):
    """A problem the user should be told about in plain language."""


class InsufficientInventoryError(KitchenError):
    pass


class IngredientNotFoundError(KitchenError):
    pass


class RecordNotFoundError(KitchenError):
    pass


class StorageError(KitchenError):
    """Saving failed. Carries the unsaved record, if any, so it can still be shown to the user."""

    def __init__(self, message: str, record: HistoryRecord | None = None) -> None:
        super().__init__(message)
        self._record = record

    @property
    def record(self) -> HistoryRecord | None:
        return self._record


class RecordComparison:
    """
    A saved recipe re-checked against today's inventory: is it still cookable, did the verdict change,
    and what is now missing that was in stock when the recipe was suggested?
    """

    def __init__(self, record: HistoryRecord, current: Evaluation, request_inferred: bool) -> None:
        self._record = record
        self._current = current
        self._request_inferred = request_inferred

    @property
    def record(self) -> HistoryRecord:
        return self._record

    @property
    def saved(self) -> Evaluation:
        return self._record.evaluation

    @property
    def current(self) -> Evaluation:
        return self._current

    @property
    def request_inferred(self) -> bool:
        """True for Phase 1 records, saved before the original request was stored."""
        return self._request_inferred

    @property
    def still_cookable(self) -> bool:
        return self._current.outcome != Outcome.REJECTED

    @property
    def verdict_changed(self) -> bool:
        return self._current.outcome != self.saved.outcome

    @property
    def newly_missing(self) -> tuple[str, ...]:
        before = set(self.saved.matched_ingredients)
        return tuple(i for i in self._current.missing_ingredients if i in before)

    @property
    def match_change(self) -> int:
        return self._current.match_percentage - self.saved.match_percentage

    def rule_changes(self) -> list[tuple[str, RuleResult | None, RuleResult]]:
        """(rule name, result when saved or None for Phase 1 records, result today) for every rule."""
        saved = {result.rule_name: result for result in self.saved.rule_results}
        return [(result.rule_name, saved.get(result.rule_name), result) for result in self._current.rule_results]


class KitchenService:
    """
    Coordinates the managers. Associated with (not owning) each manager: they are created by the
    application and handed in, so tests can supply a stub AI client or temporary data files.
    """

    MIN_INGREDIENTS = 2
    EXPIRING_SOON_DAYS = 3

    def __init__(self, data_manager: DataManager, ai_manager: AIManager[RecipeJob, Recipe],
                 logic_manager: LogicManager, clock: Callable[[], date] = date.today) -> None:
        self._data = data_manager
        self._ai = ai_manager
        self._logic = logic_manager
        self._clock = clock

    def today(self) -> date:
        return self._clock()

    def inventory(self) -> Inventory:
        return self._data.load_inventory()

    def expiring_soon(self, days: int = EXPIRING_SOON_DAYS) -> list[Ingredient]:
        return self.inventory().expiring_within(days, self.today())

    def add_ingredient(self, ingredient: Ingredient) -> Ingredient:
        inventory = self.inventory()
        stored = inventory.add_or_update(ingredient)
        if not self._data.save_inventory(inventory):
            raise StorageError("The inventory could not be saved. Please try again.")
        return stored

    def remove_ingredient(self, name: str) -> Ingredient:
        inventory = self.inventory()
        removed = inventory.remove(name)
        if removed is None:
            raise IngredientNotFoundError(f"'{name}' is not in your inventory.")
        if not self._data.save_inventory(inventory):
            raise StorageError("The inventory could not be saved. Nothing was removed.")
        return removed

    def generate_recipe(self, request: RecipeRequest) -> HistoryRecord:
        """
        The core pipeline. Every request goes through the AI; the validated recipe is judged by the
        logic layer and saved. Raises InsufficientInventoryError, AIProcessingError or StorageError.
        """
        inventory = self.inventory()
        if len(inventory) < self.MIN_INGREDIENTS:
            raise InsufficientInventoryError(
                f"Add at least {self.MIN_INGREDIENTS} ingredients to your inventory so the AI can suggest a meal.")
        job = RecipeJob(request, inventory)
        recipe = self._ai.process(job)
        evaluation = self._logic.evaluate(recipe, job, self.today())
        record = HistoryRecord(recipe, evaluation, request)
        if not self._data.save(record):
            raise StorageError("The recipe was generated but could not be saved to your history.", record)
        return record

    def history(self, record_filter: RecordFilter | None = None) -> list[HistoryRecord]:
        return self._data.query(record_filter or AllFilters())

    def compare_with_current(self, record_id: str) -> RecordComparison:
        """Loads one saved recipe and re-evaluates it against today's inventory with the same rules."""
        record = self._data.get(record_id)
        if record is None:
            raise RecordNotFoundError("That recipe is not in your history.")
        request = record.request or self._infer_request(record)
        current = self._logic.evaluate(record.recipe, RecipeJob(request, self.inventory()), self.today())
        return RecordComparison(record, current, request_inferred=record.request is None)

    @staticmethod
    def _infer_request(record: HistoryRecord) -> RecipeRequest:
        """Phase 1 records did not store the request: re-check with no allergies and the recipe's own time."""
        meal_type = record.recipe.meal_type if record.recipe.meal_type in RecipeRequest.MEAL_TYPES else "Dinner"
        minutes = min(max(record.recipe.cook_time_mins, 1), RecipeRequest.MAX_COOK_TIME)
        return RecipeRequest(meal_type, minutes)
