import json
import logging
import os
import tempfile
import unittest
from datetime import date, datetime

from src.data_manager import (
    AllFilters, DataManager, IngredientFilter, JsonFileStore, MealTypeFilter, OutcomeFilter, RecordFilter,
)
from src.models import Evaluation, HistoryRecord, Ingredient, Inventory, Outcome, Recipe


class Factory:
    @staticmethod
    def record(name: str, meal: str, used: list[str], outcome: Outcome, created: datetime) -> HistoryRecord:
        evaluation = Evaluation(outcome, outcome.value, "", 1.0, used, [], [], 0.0, [], 0, True, True)
        return HistoryRecord(Recipe(name, meal, 10, used, [], ["Cook."]), evaluation, created_at=created)


class DataManagerTestCase(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.inventory_path = os.path.join(self.dir, "inventory.json")
        self.history_path = os.path.join(self.dir, "history.json")
        self.data = DataManager(self.inventory_path, self.history_path)

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def write(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


class InventoryPersistenceTests(DataManagerTestCase):
    def test_missing_file_gives_empty_inventory(self):
        self.assertEqual(len(self.data.load_inventory()), 0)

    def test_save_and_reload_round_trip(self):
        inventory = Inventory([Ingredient("Eggs", 6, "pcs", date(2026, 11, 5))])
        self.assertTrue(self.data.save_inventory(inventory))
        self.assertFalse(os.path.exists(self.inventory_path + ".tmp"), "Temp file is swapped into place")
        reloaded = self.data.load_inventory()
        self.assertEqual([i.to_dict() for i in reloaded], [i.to_dict() for i in inventory])

    def test_corrupt_file_is_quarantined_not_overwritten(self):
        self.write(self.inventory_path, '[{"name": "Milk", "quantity": 1')
        self.assertEqual(len(self.data.load_inventory()), 0)
        backups = [n for n in os.listdir(self.dir) if ".corrupt-" in n]
        self.assertEqual(len(backups), 1)
        self.assertFalse(os.path.exists(self.inventory_path))
        with open(os.path.join(self.dir, backups[0]), encoding="utf-8") as f:
            self.assertIn("Milk", f.read(), "Original bytes kept for recovery")

    def test_wrong_shape_and_invalid_rows_are_skipped(self):
        self.write(self.inventory_path, "   ")
        self.assertEqual(len(self.data.load_inventory()), 0)
        self.write(self.inventory_path, json.dumps({"name": "not a list"}))
        self.assertEqual(len(self.data.load_inventory()), 0)
        self.write(self.inventory_path, json.dumps([
            {"name": "Eggs", "quantity": 6, "unit": "pcs", "expiry_date": "2026-11-05"},
            {"name": "", "quantity": 1}, {"quantity": 1}, {"name": "Rice", "quantity": "lots"}, "garbage", 42,
        ]))
        self.assertEqual([i.name for i in self.data.load_inventory()], ["Eggs"])

    def test_write_failure_returns_false_and_cleans_up(self):
        broken = DataManager(os.path.join(self.inventory_path, "nested.json"), self.history_path)
        self.write(self.inventory_path, "[]")
        self.assertFalse(broken.save_inventory(Inventory([Ingredient("Rice", 1, "kg", None)])))
        store = JsonFileStore(os.path.join(self.dir, "set.json"))
        self.assertFalse(store.write_rows([{"bad": {1, 2}}]), "Unserialisable data returns False")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "set.json.tmp")))


class HistoryPersistenceTests(DataManagerTestCase):
    def setUp(self):
        super().setUp()
        self.omelette = Factory.record("Omelette", "Breakfast", ["Eggs", "Cheddar"], Outcome.ACCEPTED,
                                    datetime(2026, 11, 1, 8, 0))
        self.curry = Factory.record("Curry", "Dinner", ["Chicken", "Rice"], Outcome.FLAGGED,
                                 datetime(2026, 11, 2, 19, 0))
        for record in (self.omelette, self.curry):
            self.assertTrue(self.data.save(record))

    def test_load_newest_first_and_get_by_id(self):
        self.assertEqual([r.recipe.name for r in self.data.load()], ["Curry", "Omelette"])
        self.assertEqual(self.data.get(self.omelette.id).recipe.name, "Omelette")
        self.assertIsNone(self.data.get("does-not-exist"))

    def test_query_with_filter_objects(self):
        self.assertEqual([r.recipe.name for r in self.data.query(MealTypeFilter("breakfast"))], ["Omelette"])
        self.assertEqual([r.recipe.name for r in self.data.query(IngredientFilter("chick"))], ["Curry"])
        self.assertEqual([r.recipe.name for r in self.data.query(OutcomeFilter(Outcome.FLAGGED))], ["Curry"])
        both = AllFilters([MealTypeFilter("Dinner"), OutcomeFilter(Outcome.ACCEPTED)])
        self.assertEqual(self.data.query(both), [])
        self.assertEqual(len(self.data.query(AllFilters())), 2, "No filters matches everything")

    def test_query_skips_records_that_break_a_filter(self):
        class Fussy(RecordFilter):
            def matches(self, record):
                if record.recipe.name == "Curry":
                    raise KeyError("missing field")
                return True

        self.assertEqual([r.recipe.name for r in self.data.query(Fussy())], ["Omelette"])

    def test_corrupt_history_gives_empty_list(self):
        self.write(self.history_path, "{not json")
        self.assertEqual(self.data.load(), [])
        self.assertEqual(self.data.query(AllFilters()), [])


if __name__ == "__main__":
    unittest.main()
