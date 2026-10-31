import json
import logging
import os
import tempfile
import unittest
from datetime import date, timedelta

from src.ai_manager import AIConnectionError, AIProcessingError, RecipeAIManager
from src.data_manager import DataManager, MealTypeFilter
from src.kitchen_service import (
    IngredientNotFoundError, InsufficientInventoryError, KitchenService, RecordNotFoundError, StorageError,
)
from src.logic_manager import LogicManager
from src.models import Ingredient, Outcome, RecipeRequest
from tests.sample_ai_responses import SampleResponses, StubAIClient

TODAY = date(2026, 11, 2)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.inventory_path = os.path.join(self._tmp.name, "inventory.json")
        self.history_path = os.path.join(self._tmp.name, "history.json")
        self.data = DataManager(self.inventory_path, self.history_path)
        self.data.save_inventory(SampleResponses.inventory(TODAY))
        self.client = StubAIClient([SampleResponses.ACCEPTED])
        self.service = self.make_service(self.client)

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def make_service(self, client, data=None):
        ai = RecipeAIManager(client, ("model-a", "model-b"), sleep=lambda _: None)
        return KitchenService(data or self.data, ai, LogicManager(), clock=lambda: TODAY)


class KitchenServiceTests(ServiceTestCase):
    def test_generate_runs_pipeline_and_saves_request_with_record(self):
        record = self.service.generate_recipe(RecipeRequest("Breakfast", 20, ["nuts"]))
        self.assertEqual(record.evaluation.outcome, Outcome.ACCEPTED)
        self.assertEqual(len(self.client.calls), 1, "Every request goes through the AI")
        self.assertIn("Spinach", self.client.calls[0][0])
        saved = self.data.get(record.id)
        self.assertEqual(saved.request.allergies, ("nuts",))
        self.assertEqual(saved.evaluation.expiry_priority_score, 100.0)

    def test_generate_needs_two_ingredients_and_never_calls_ai(self):
        for name in ("Eggs", "Cheddar Cheese", "Spinach", "Bread", "Chicken Breast"):
            self.service.remove_ingredient(name)
        with self.assertRaises(InsufficientInventoryError):
            self.service.generate_recipe(RecipeRequest("Dinner", 30))
        self.assertEqual(self.client.calls, [])

    def test_ai_failure_saves_nothing(self):
        service = self.make_service(StubAIClient([AIConnectionError("network down")]))
        with self.assertRaises(AIProcessingError):
            service.generate_recipe(RecipeRequest("Dinner", 30))
        self.assertEqual(self.data.load(), [])

    def test_storage_failure_still_returns_the_record(self):
        broken = DataManager(self.inventory_path, os.path.join(self.inventory_path, "history.json"))
        with self.assertRaises(StorageError) as ctx:
            self.make_service(StubAIClient([SampleResponses.ACCEPTED]), broken).generate_recipe(
                RecipeRequest("Breakfast", 20))
        self.assertEqual(ctx.exception.record.recipe.name, "Spinach & Cheddar Omelette")

    def test_inventory_add_restock_remove(self):
        tofu = self.service.add_ingredient(Ingredient("Tofu", 300, "g", TODAY + timedelta(days=8)))
        self.assertEqual(tofu.id, "ing-007")
        self.service.add_ingredient(Ingredient("tofu", 600, "g", TODAY + timedelta(days=9)))
        self.assertEqual(self.service.inventory().find("Tofu").quantity, 600)
        self.assertEqual(self.service.remove_ingredient("TOFU").name, "Tofu")
        with self.assertRaises(IngredientNotFoundError):
            self.service.remove_ingredient("Ghost Pepper")

    def test_expiring_soon(self):
        self.assertEqual([i.name for i in self.service.expiring_soon()], ["Spinach", "Eggs", "Cheddar Cheese", "Milk"])

    def test_history_filtering(self):
        self.service.generate_recipe(RecipeRequest("Breakfast", 20))
        self.assertEqual(len(self.service.history()), 1)
        self.assertEqual(self.service.history(MealTypeFilter("Dinner")), [])


class RecordComparisonTests(ServiceTestCase):
    """The new feature: open one saved recipe and re-check it against today's inventory."""

    def test_unchanged_inventory_gives_same_verdict(self):
        record = self.service.generate_recipe(RecipeRequest("Breakfast", 20))
        comparison = self.service.compare_with_current(record.id)
        self.assertEqual(comparison.record.recipe.name, "Spinach & Cheddar Omelette")
        self.assertFalse(comparison.verdict_changed)
        self.assertTrue(comparison.still_cookable)
        self.assertEqual(comparison.match_change, 0)
        self.assertFalse(comparison.request_inferred)

    def test_using_up_ingredients_changes_the_verdict(self):
        record = self.service.generate_recipe(RecipeRequest("Breakfast", 20))
        for name in ("Eggs", "Cheddar Cheese", "Spinach"):
            self.service.remove_ingredient(name)
        comparison = self.service.compare_with_current(record.id)
        self.assertEqual(comparison.saved.outcome, Outcome.ACCEPTED, "Saved verdict is never rewritten")
        self.assertEqual(comparison.current.outcome, Outcome.REJECTED)
        self.assertTrue(comparison.verdict_changed)
        self.assertFalse(comparison.still_cookable)
        self.assertEqual(len(comparison.newly_missing), 3)
        self.assertEqual(comparison.match_change, -100)

    def test_unknown_record(self):
        with self.assertRaises(RecordNotFoundError):
            self.service.compare_with_current("nope")

    def test_phase1_record_without_request_is_rechecked_with_inferred_request(self):
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump([{
                "created_at": "2026-09-22 17:38:01",
                "recipe": json.loads(SampleResponses.ACCEPTED),
                "evaluation": {"outcome": "FLAGGED", "match_ratio": 0.5, "matched_ingredients": []},
            }], f)
        record = self.service.history()[0]
        comparison = self.service.compare_with_current(record.id)
        self.assertTrue(comparison.request_inferred)
        self.assertEqual(comparison.current.outcome, Outcome.ACCEPTED)
        self.assertTrue(comparison.verdict_changed)


if __name__ == "__main__":
    unittest.main()
