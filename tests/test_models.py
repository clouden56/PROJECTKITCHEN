import unittest
from datetime import date, datetime

from src.models import (
    Evaluation, HistoryRecord, Ingredient, Inventory, Outcome, Recipe, RecipeRequest, RescuedItem, RuleResult,
)

TODAY = date(2026, 11, 2)


class Factory:
    @staticmethod
    def ingredient(name: str, days: int | None = 5, quantity: float = 1) -> Ingredient:
        expiry = date.fromordinal(TODAY.toordinal() + days) if days is not None else None
        return Ingredient(name, quantity, "pcs", expiry)


class IngredientTests(unittest.TestCase):
    def test_rejects_invalid_values(self):
        for bad in [("", 1), ("Eggs", 0), ("Eggs", -2), ("Eggs", float("inf")), ("Eggs", float("nan")), ("Eggs", True)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Ingredient(bad[0], bad[1], "pcs", TODAY)
        with self.assertRaises(ValueError):
            Ingredient("Eggs", 1, "pcs", TODAY, location="Garage")

    def test_expiry_status_and_days(self):
        self.assertEqual(Factory.ingredient("A", -1).expiry_status(TODAY), "expired")
        self.assertEqual(Factory.ingredient("A", 0).expiry_status(TODAY), "today")
        self.assertEqual(Factory.ingredient("A", 3).expiry_status(TODAY), "soon")
        self.assertEqual(Factory.ingredient("A", 4).expiry_status(TODAY), "ok")
        unknown = Factory.ingredient("A", None)
        self.assertEqual(unknown.expiry_status(TODAY), "unknown")
        self.assertEqual(unknown.days_until_expiry(TODAY), 999)

    def test_round_trip_and_lenient_date_parsing(self):
        item = Ingredient("Milk", 500, "ml", TODAY, "Fridge", "ing-004")
        self.assertEqual(Ingredient.from_dict(item.to_dict()).to_dict(), item.to_dict())
        self.assertEqual(item.to_dict()["quantity"], 500)
        self.assertIsNone(Ingredient.from_dict({"name": "Rice", "quantity": 1, "expiry_date": "12/10/2026"}).expiry_date)

    def test_attributes_are_read_only(self):
        item = Factory.ingredient("Eggs")
        with self.assertRaises(AttributeError):
            item.name = "Bacon"


class InventoryTests(unittest.TestCase):
    def test_add_assigns_next_id_and_restocks_by_name(self):
        inventory = Inventory([Ingredient("Eggs", 6, "pcs", TODAY, ingredient_id="ing-007")])
        tofu = inventory.add_or_update(Factory.ingredient("Tofu"))
        self.assertEqual(tofu.id, "ing-008", "Next id follows the highest existing id, not the count")
        restocked = inventory.add_or_update(Factory.ingredient("eggs", 9, quantity=12))
        self.assertEqual(len(inventory), 2)
        self.assertEqual(restocked.quantity, 12)
        self.assertEqual(restocked.id, "ing-007")

    def test_remove_and_aggregated_items_outlive_inventory(self):
        eggs = Factory.ingredient("Eggs")
        inventory = Inventory([eggs])
        self.assertIs(inventory.remove("EGGS"), eggs)
        self.assertIsNone(inventory.remove("Eggs"))
        self.assertEqual(eggs.name, "Eggs", "Removed ingredient still exists independently")

    def test_expiring_within_sorts_soonest_first(self):
        inventory = Inventory([Factory.ingredient("Late", 10), Factory.ingredient("Soon", 2),
                               Factory.ingredient("Gone", -1), Factory.ingredient("Unknown", None)])
        self.assertEqual([i.name for i in inventory.expiring_within(3, TODAY)], ["Gone", "Soon"])


class RecipeRequestTests(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(ValueError):
            RecipeRequest("Brunch", 20)
        for minutes in (0, 601, 2.5, True):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                RecipeRequest("Lunch", minutes)

    def test_cleans_lists(self):
        request = RecipeRequest("Lunch", 20, allergies=[" nuts ", "", "nuts", "dairy"])
        self.assertEqual(request.allergies, ("nuts", "dairy"))
        self.assertEqual(RecipeRequest.from_dict(request.to_dict()).to_dict(), request.to_dict())


class RecipeTests(unittest.TestCase):
    def test_recipe_composes_numbered_steps(self):
        recipe = Recipe("Toast", "Snack", 5, ["Bread"], [], ["Slice bread.", "Toast it."])
        self.assertEqual([(s.number, s.text) for s in recipe.steps], [(1, "Slice bread."), (2, "Toast it.")])
        self.assertEqual(Recipe.from_dict(recipe.to_dict()).to_dict(), recipe.to_dict())


class HistoryRecordTests(unittest.TestCase):
    def make_evaluation(self) -> Evaluation:
        return Evaluation(Outcome.ACCEPTED, "OPTIMAL_MATCH", "ok", 1.0, ["Bread"], [], [], 35.0,
                          [RescuedItem("Bread", 2, 4, "slices")], 400, True, True,
                          [RuleResult("Allergen safety", True)])

    def test_round_trip_keeps_id_request_and_rule_results(self):
        record = HistoryRecord(Recipe("Toast", "Snack", 5, ["Bread"], [], ["Toast it."]), self.make_evaluation(),
                               RecipeRequest("Snack", 10, ["nuts"]), datetime(2026, 11, 1, 9, 30))
        restored = HistoryRecord.from_dict(record.to_dict())
        self.assertEqual(restored.to_dict(), record.to_dict())
        self.assertEqual(restored.evaluation.rule_results[0].rule_name, "Allergen safety")

    def test_legacy_record_without_id_gets_stable_id(self):
        legacy = {"created_at": "2026-09-22 17:38:01",
                  "recipe": {"recipe_name": "Omelette", "meal_type": "Breakfast", "ingredients_used": ["Eggs"]},
                  "evaluation": {"outcome": "ACCEPTED"}}
        first, second = HistoryRecord.from_dict(legacy), HistoryRecord.from_dict(legacy)
        self.assertEqual(first.id, second.id)
        self.assertIsNone(first.request)
        self.assertEqual(first.evaluation.rule_results, ())


if __name__ == "__main__":
    unittest.main()
