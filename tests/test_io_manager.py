import unittest
from datetime import date

from src.data_manager import AllFilters
from src.io_manager import ChoiceField, DateField, FieldError, IOManager, ListField, NumberField, TextField
from src.models import Evaluation, HistoryRecord, Ingredient, Outcome, Recipe

TODAY = date(2026, 11, 2)
VALID_INGREDIENT = {"name": " Tofu ", "quantity": "300", "unit": "g", "location": "fridge", "expiry_date": "2026-11-20"}
VALID_REQUEST = {"meal_type": "dinner", "max_cook_time_mins": "30", "allergies": "peanuts, , dairy ",
                 "mandatory_ingredients": "", "notes": "one-pot"}


class FieldTests(unittest.TestCase):
    def test_required_and_optional_blanks(self):
        with self.assertRaises(FieldError):
            TextField("name", "Name", 10).clean("   ")
        self.assertEqual(TextField("notes", "Notes", 10, required=False).clean(None), "")
        self.assertEqual(ListField("allergies", "Allergies").clean(""), [])

    def test_number_field_rejects_bad_values(self):
        field = NumberField("qty", "Quantity", maximum=1000)
        for raw in ("abc", "0", "-3", "inf", "nan", "1001"):
            with self.subTest(raw=raw), self.assertRaises(FieldError):
                field.clean(raw)
        self.assertEqual(field.clean("2.5"), 2.5)
        with self.assertRaises(FieldError):
            NumberField("mins", "Minutes", whole=True).clean("1.5")

    def test_date_choice_and_list_fields(self):
        for raw in ("2026/11/20", "20-11-2026", "2026-02-30", "tomorrow"):
            with self.subTest(raw=raw), self.assertRaises(FieldError):
                DateField("expiry", "Expiry").clean(raw)
        self.assertEqual(ChoiceField("meal", "Meal", ("Lunch", "Dinner")).clean("DINNER"), "Dinner")
        with self.assertRaises(FieldError):
            ChoiceField("meal", "Meal", ("Lunch",)).clean("Brunch")
        with self.assertRaises(FieldError):
            ListField("allergies", "Allergies", max_items=2).clean("a, b, c")


class IOManagerTests(unittest.TestCase):
    def setUp(self):
        self.io = IOManager()

    def test_valid_ingredient_form_becomes_typed_ingredient(self):
        result = self.io.parse_ingredient(VALID_INGREDIENT)
        self.assertTrue(result.ok)
        self.assertEqual((result.value.name, result.value.quantity, result.value.location, result.value.expiry_date),
                         ("Tofu", 300.0, "Fridge", date(2026, 11, 20)))

    def test_invalid_ingredient_form_reports_every_field_and_keeps_input(self):
        result = self.io.parse_ingredient({"name": "", "quantity": "zero", "unit": "g",
                                           "location": "Garage", "expiry_date": "12-10-2026"})
        self.assertFalse(result.ok)
        self.assertIsNone(result.value)
        self.assertEqual(set(result.errors), {"name", "quantity", "location", "expiry_date"})
        self.assertEqual(result.submitted["quantity"], "zero")

    def test_recipe_request_form(self):
        result = self.io.parse_recipe_request(VALID_REQUEST)
        self.assertTrue(result.ok)
        self.assertEqual(result.value.meal_type, "Dinner")
        self.assertEqual(result.value.allergies, ("peanuts", "dairy"))
        bad = self.io.parse_recipe_request({**VALID_REQUEST, "max_cook_time_mins": "601", "meal_type": "Brunch"})
        self.assertEqual(set(bad.errors), {"max_cook_time_mins", "meal_type"})

    def test_history_filter_ignores_unknown_values(self):
        record_filter, selected = self.io.parse_history_filter({"meal_type": "brunch", "outcome": "accepted",
                                                                "ingredient": "egg"})
        self.assertIsInstance(record_filter, AllFilters)
        self.assertEqual(selected, {"meal_type": "", "ingredient": "egg", "outcome": "ACCEPTED"})
        self.assertEqual(len(record_filter.filters), 2)
        evaluation = Evaluation(Outcome.ACCEPTED, "", "", 1, [], [], [], 0, [], 0, True, True)
        record = HistoryRecord(Recipe("Egg Fried Rice", "Dinner", 10, ["2 Eggs"], [], ["Cook."]), evaluation)
        self.assertTrue(record_filter.matches(record))

    def test_display_helpers(self):
        self.assertEqual(self.io.expiry_badge(Ingredient("Milk", 1, "l", TODAY), TODAY), ("Expires today", "today"))
        self.assertEqual(self.io.expiry_badge(Ingredient("Milk", 1, "l", date(2026, 11, 3)), TODAY), ("1 day left", "soon"))
        self.assertEqual(self.io.expiry_badge(Ingredient("Rice", 1, "kg", None), TODAY), ("No date", "unknown"))
        self.assertEqual(self.io.outcome_style(Outcome.REJECTED), "rejected")
        self.assertEqual(IOManager.format_quantity(0.5, "kg"), "0.5 kg")
        self.assertEqual(IOManager.format_quantity(None, "pcs"), "pcs")


if __name__ == "__main__":
    unittest.main()
