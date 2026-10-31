import logging
import os
import tempfile
import unittest
from datetime import date

from src.ai_manager import AIConnectionError, RecipeAIManager
from src.data_manager import DataManager
from src.io_manager import IOManager
from src.kitchen_service import KitchenService
from src.logic_manager import LogicManager
from src.web_app import WebApp
from tests.sample_ai_responses import SampleResponses, StubAIClient

TODAY = date(2026, 11, 2)


class WebTestCase(unittest.TestCase):
    """Runs the real Flask app against temporary data files and a scripted AI client."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.data = DataManager(os.path.join(self._tmp.name, "inventory.json"),
                                os.path.join(self._tmp.name, "history.json"))
        self.data.save_inventory(SampleResponses.inventory(TODAY))
        self.ai_client = StubAIClient([SampleResponses.ACCEPTED])
        ai = RecipeAIManager(self.ai_client, ("model-a",), sleep=lambda _: None)
        self.service = KitchenService(self.data, ai, LogicManager(), clock=lambda: TODAY)
        self.app = WebApp(self.service, IOManager(), secret_key="test")
        self.app.flask.testing = True
        self.client = self.app.flask.test_client()

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def text(self, response) -> str:
        return response.get_data(as_text=True)

    def generate(self, **overrides):
        form = {"meal_type": "Breakfast", "max_cook_time_mins": "20", "allergies": "nuts",
                "mandatory_ingredients": "", "notes": ""}
        form.update(overrides)
        return self.client.post("/recipes", data=form)


class PageTests(WebTestCase):
    def test_dashboard_summarises_inventory_and_expiring_items(self):
        page = self.text(self.client.get("/"))
        self.assertIn("items tracked", page)
        self.assertIn("Spinach", page)
        self.assertIn("Expires today", page)

    def test_health_and_not_found(self):
        self.assertEqual(self.client.get("/health").get_json(), {"status": "ok"})
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Page not found", self.text(response))

    def test_inventory_lists_items_soonest_first_and_filters_expiring(self):
        page = self.text(self.client.get("/inventory"))
        self.assertLess(page.index("Spinach"), page.index("Bread"))
        expiring = self.text(self.client.get("/inventory?view=expiring"))
        self.assertIn("Milk", expiring)
        self.assertNotIn("Chicken Breast", expiring)


class InventoryFormTests(WebTestCase):
    def test_add_valid_item(self):
        response = self.client.post("/inventory", data={"name": "Tofu", "quantity": "300", "unit": "g",
                                                         "location": "Fridge", "expiry_date": "2026-11-20"},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Saved Tofu", self.text(response))
        self.assertIsNotNone(self.service.inventory().find("Tofu"))

    def test_invalid_item_is_redisplayed_with_errors(self):
        response = self.client.post("/inventory", data={"name": "Tofu", "quantity": "lots", "unit": "",
                                                         "location": "Fridge", "expiry_date": "2026-02-30"})
        self.assertEqual(response.status_code, 422)
        page = self.text(response)
        self.assertIn("Quantity must be a number", page)
        self.assertIn("real date", page)
        self.assertIn('value="lots"', page, "User's input is kept")
        self.assertIsNone(self.service.inventory().find("Tofu"))

    def test_user_text_is_escaped(self):
        self.client.post("/inventory", data={"name": "<script>alert(1)</script>", "quantity": "1", "unit": "pcs",
                                             "location": "Pantry", "expiry_date": "2026-11-20"})
        page = self.text(self.client.get("/inventory"))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_remove_item(self):
        page = self.text(self.client.post("/inventory/remove", data={"name": "Milk"}, follow_redirects=True))
        self.assertIn("Removed Milk", page)
        page = self.text(self.client.post("/inventory/remove", data={"name": "Milk"}, follow_redirects=True))
        self.assertIn("not in your inventory", page)


class RecipeGenerationTests(WebTestCase):
    def test_generate_saves_record_and_shows_it_in_history(self):
        response = self.generate()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.ai_client.calls), 1)
        history = self.text(self.client.get("/history"))
        self.assertIn("Spinach &amp; Cheddar Omelette", history)
        self.assertIn("ACCEPTED", history)

    def test_invalid_request_never_reaches_the_ai(self):
        response = self.generate(max_cook_time_mins="0", meal_type="Brunch")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.ai_client.calls, [])
        self.assertIn("Meal type must be one of", self.text(response))

    def test_ai_failure_shows_message_and_saves_nothing(self):
        self.ai_client = StubAIClient([AIConnectionError("network down")])
        ai = RecipeAIManager(self.ai_client, ("model-a",), sleep=lambda _: None)
        app = WebApp(KitchenService(self.data, ai, LogicManager(), clock=lambda: TODAY), IOManager(), "test")
        response = app.flask.test_client().post("/recipes", data={"meal_type": "Dinner", "max_cook_time_mins": "30"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("AI service is unavailable", self.text(response))
        self.assertEqual(self.data.load(), [])

    def test_too_few_ingredients(self):
        for name in ("Eggs", "Cheddar Cheese", "Spinach", "Bread", "Chicken Breast"):
            self.service.remove_ingredient(name)
        self.assertIn("Add at least 2", self.text(self.client.get("/recipes/new")))
        response = self.generate()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.ai_client.calls, [])

    def test_history_filters(self):
        self.generate()
        self.assertIn("Omelette", self.text(self.client.get("/history?meal_type=Breakfast&outcome=ACCEPTED")))
        page = self.text(self.client.get("/history?meal_type=Dinner"))
        self.assertIn("No saved recipes match", page)
        self.assertIn("Omelette", self.text(self.client.get("/history?meal_type=nonsense")),
                      "Unknown filter values are ignored")


if __name__ == "__main__":
    unittest.main()
