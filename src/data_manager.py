"""
Data Manager - persistence layer.

Stores the inventory and the recipe history in flat JSON files and answers history queries.
A missing, empty, corrupt or unwritable file never crashes the application: the problem is logged,
corrupt files are moved aside for recovery, and callers get an empty result or a False return value.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, Iterable, TypeVar

from src.models import HistoryRecord, Ingredient, Inventory, Outcome

logger = logging.getLogger(__name__)

T = TypeVar("T")


class JsonFileStore:
    """Reads and writes one JSON array file safely. Knows nothing about what the rows mean."""

    def __init__(self, path: str) -> None:
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def read_rows(self) -> list[dict[str, Any]]:
        """Returns the file's JSON objects; [] if the file is missing, empty, corrupt or the wrong shape."""
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as file:
                content = file.read().strip()
        except (OSError, UnicodeDecodeError) as err:
            logger.error("Could not read %s: %s", self._path, err)
            return []
        if not content:
            return []
        try:
            data = json.loads(content)
        except json.JSONDecodeError as err:
            logger.error("Corrupt JSON in %s: %s", self._path, err)
            self._quarantine()
            return []
        if not isinstance(data, list):
            logger.error("%s does not contain a JSON array; ignoring it.", self._path)
            return []
        return [row for row in data if isinstance(row, dict)]

    def write_rows(self, rows: list[dict[str, Any]]) -> bool:
        """Writes to a temporary file and swaps it in atomically, so a failed write never corrupts data."""
        directory = os.path.dirname(self._path)
        temp_path = f"{self._path}.tmp"
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(rows, file, indent=2, ensure_ascii=False)
            os.replace(temp_path, self._path)
            return True
        except (OSError, TypeError, ValueError) as err:
            logger.error("Could not write %s: %s", self._path, err)
            self._discard(temp_path)
            return False

    def _quarantine(self) -> None:
        backup = f"{self._path}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
        try:
            os.replace(self._path, backup)
            logger.warning("Corrupt file moved to %s for manual recovery.", backup)
        except OSError as err:
            logger.error("Could not move corrupt file %s aside: %s", self._path, err)

    @staticmethod
    def _discard(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


class Repository(ABC, Generic[T]):
    """Interface for loading and saving a whole collection of domain objects."""

    @abstractmethod
    def load(self) -> list[T]:
        """Returns every stored object; never raises for missing or corrupt storage."""

    @abstractmethod
    def save(self, items: Iterable[T]) -> bool:
        """Replaces the stored collection; returns False if it could not be written."""


class JsonRepository(Repository[T], ABC):
    """
    Shared JSON persistence for any domain object. Subclasses only say how one object maps to a dict.
    Composes its JsonFileStore: the store is created here and lives and dies with the repository.
    """

    def __init__(self, path: str) -> None:
        self._store = JsonFileStore(path)

    @property
    def path(self) -> str:
        return self._store.path

    def load(self) -> list[T]:
        items = []
        for row in self._store.read_rows():
            try:
                items.append(self._from_dict(row))
            except (KeyError, TypeError, ValueError) as err:
                logger.warning("Skipping invalid record in %s: %s", self._store.path, err)
        return items

    def save(self, items: Iterable[T]) -> bool:
        return self._store.write_rows([self._to_dict(item) for item in items])

    @abstractmethod
    def _from_dict(self, row: dict[str, Any]) -> T:
        """Builds one domain object; raises KeyError/TypeError/ValueError for invalid rows."""

    @abstractmethod
    def _to_dict(self, item: T) -> dict[str, Any]:
        """Serialises one domain object."""


class InventoryRepository(JsonRepository[Ingredient]):
    def _from_dict(self, row: dict[str, Any]) -> Ingredient:
        return Ingredient.from_dict(row)

    def _to_dict(self, item: Ingredient) -> dict[str, Any]:
        return item.to_dict()


class HistoryRepository(JsonRepository[HistoryRecord]):
    def _from_dict(self, row: dict[str, Any]) -> HistoryRecord:
        return HistoryRecord.from_dict(row)

    def _to_dict(self, item: HistoryRecord) -> dict[str, Any]:
        return item.to_dict()

    def add(self, record: HistoryRecord) -> bool:
        return self.save([*self.load(), record])


class RecordFilter(ABC):
    """Interface for a history search criterion."""

    @abstractmethod
    def matches(self, record: HistoryRecord) -> bool:
        """True if the record satisfies this criterion."""

    def __call__(self, record: HistoryRecord) -> bool:
        return self.matches(record)


class MealTypeFilter(RecordFilter):
    def __init__(self, meal_type: str) -> None:
        self._meal_type = meal_type.strip().lower()

    def matches(self, record: HistoryRecord) -> bool:
        return record.recipe.meal_type.strip().lower() == self._meal_type


class IngredientFilter(RecordFilter):
    def __init__(self, ingredient: str) -> None:
        self._needle = ingredient.strip().lower()

    def matches(self, record: HistoryRecord) -> bool:
        return any(self._needle in used.lower() for used in record.recipe.ingredients_used)


class OutcomeFilter(RecordFilter):
    def __init__(self, outcome: Outcome) -> None:
        self._outcome = outcome

    def matches(self, record: HistoryRecord) -> bool:
        return record.evaluation.outcome == self._outcome


class AllFilters(RecordFilter):
    """Matches records that satisfy every one of its filters (no filters matches everything)."""

    def __init__(self, filters: Iterable[RecordFilter] = ()) -> None:
        self._filters = tuple(filters)

    @property
    def filters(self) -> tuple[RecordFilter, ...]:
        return self._filters

    def matches(self, record: HistoryRecord) -> bool:
        return all(f.matches(record) for f in self._filters)


class DataManager:
    """
    Facade for all persistence. Composes one repository per data set; the rest of the
    application never touches files directly.
    """

    def __init__(self, inventory_path: str, history_path: str) -> None:
        self._inventory_repository = InventoryRepository(inventory_path)
        self._history_repository = HistoryRepository(history_path)

    def load_inventory(self) -> Inventory:
        return Inventory(self._inventory_repository.load())

    def save_inventory(self, inventory: Inventory) -> bool:
        return self._inventory_repository.save(inventory.items)

    def save(self, record: HistoryRecord) -> bool:
        """Appends an evaluated record to the history."""
        return self._history_repository.add(record)

    def load(self) -> list[HistoryRecord]:
        """All saved records, newest first."""
        return sorted(self._history_repository.load(), key=lambda r: r.created_at, reverse=True)

    def query(self, record_filter: RecordFilter) -> list[HistoryRecord]:
        """Saved records (newest first) that match the filter; a record that breaks the filter is skipped."""
        results = []
        for record in self.load():
            try:
                if record_filter(record):
                    results.append(record)
            except (AttributeError, KeyError, TypeError, ValueError) as err:
                logger.warning("Filter could not evaluate record %s: %s", record.id, err)
        return results

    def get(self, record_id: str) -> HistoryRecord | None:
        return next((r for r in self._history_repository.load() if r.id == record_id), None)
