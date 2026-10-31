import io
import json
import logging
import unittest
import urllib.error
from datetime import date
from unittest import mock

from src.ai_manager import (
    AIAuthenticationError, AIConnectionError, AIProcessingError, AIRequestRejectedError, AIResponseError,
    GeminiClient, RecipeAIManager,
)
from src.models import RecipeJob, RecipeRequest
from tests.sample_ai_responses import SampleResponses, StubAIClient

TODAY = date(2026, 11, 2)
MODELS = ("model-a", "model-b", "model-c")


class RecipeAIManagerTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.sleeps: list[float] = []
        self.job = RecipeJob(RecipeRequest("Breakfast", 20, allergies=["nuts"], mandatory_ingredients=["Eggs"]),
                             SampleResponses.inventory(TODAY))

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def manager(self, *replies):
        client = StubAIClient(replies)
        return RecipeAIManager(client, MODELS, attempts_per_model=2, sleep=self.sleeps.append), client

    def test_valid_reply_becomes_recipe(self):
        manager, client = self.manager(SampleResponses.ACCEPTED)
        recipe = manager.process(self.job)
        self.assertEqual(recipe.name, "Spinach & Cheddar Omelette")
        self.assertEqual(recipe.cook_time_mins, 15)
        self.assertEqual(len(recipe.steps), 4)
        self.assertEqual(client.models_called, ["model-a"])

    def test_prompt_carries_inventory_constraints_and_json_schema(self):
        prompt = RecipeAIManager(StubAIClient([""]), MODELS).build_prompt(self.job)
        for expected in ("Spinach (150 g, Fridge, expires 2026-11-02)", "nuts", "Eggs",
                         "20 minutes", '"recipe_name": "string"', "Respond ONLY with a JSON object"):
            self.assertIn(expected, prompt)

    def test_markdown_fenced_reply_is_accepted(self):
        manager, _ = self.manager(SampleResponses.FENCED)
        self.assertEqual(manager.process(self.job).name, "Cheese Toast")

    def test_every_malformed_reply_is_rejected_without_crashing(self):
        for label, reply in SampleResponses.MALFORMED.items():
            with self.subTest(label), self.assertRaises(AIResponseError):
                manager, _ = self.manager(reply)
                manager.validate_response(manager.parse_response(reply))

    def test_malformed_then_valid_reply_recovers(self):
        manager, client = self.manager(SampleResponses.MALFORMED["prose instead of JSON"], SampleResponses.MISSING_SOME)
        self.assertEqual(manager.process(self.job).name, "French Toast")
        self.assertEqual(len(client.calls), 2)

    def test_network_down_retries_every_model_then_fails_cleanly(self):
        manager, client = self.manager(AIConnectionError("getaddrinfo failed"))
        with self.assertRaises(AIProcessingError) as ctx:
            manager.process(self.job)
        self.assertIn("unavailable", str(ctx.exception))
        self.assertEqual(client.models_called, ["model-a", "model-a", "model-b", "model-b", "model-c", "model-c"])
        self.assertEqual(self.sleeps, [1.5, 1.5, 1.5], "Back off between attempts on the same model")

    def test_rate_limit_then_success(self):
        manager, client = self.manager(AIConnectionError("HTTP 429"), SampleResponses.ACCEPTED)
        self.assertEqual(manager.process(self.job).name, "Spinach & Cheddar Omelette")
        self.assertEqual(client.models_called, ["model-a", "model-a"])

    def test_invalid_key_aborts_immediately(self):
        manager, client = self.manager(AIAuthenticationError("API_KEY_INVALID"))
        with self.assertRaises(AIProcessingError) as ctx:
            manager.process(self.job)
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))
        self.assertEqual(len(client.calls), 1)

    def test_rejected_model_falls_through_to_next_model(self):
        manager, client = self.manager(AIRequestRejectedError("HTTP 404 model retired"), SampleResponses.ACCEPTED)
        manager.process(self.job)
        self.assertEqual(client.models_called, ["model-a", "model-b"])

    def test_requires_at_least_one_model(self):
        with self.assertRaises(ValueError):
            RecipeAIManager(StubAIClient([""]), ())


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        self.client = GeminiClient("test-key", timeout_seconds=5)

    def reply_with(self, body: bytes):
        return mock.patch("src.ai_manager.urllib.request.urlopen", return_value=io.BytesIO(body))

    def raise_with(self, error: Exception):
        return mock.patch("src.ai_manager.urllib.request.urlopen", side_effect=error)

    def test_missing_key_fails_before_any_network_call(self):
        with mock.patch("src.ai_manager.urllib.request.urlopen") as urlopen, self.assertRaises(AIAuthenticationError):
            GeminiClient("").generate("prompt", "model")
        urlopen.assert_not_called()

    def test_extracts_text_and_sends_key_in_header_not_url(self):
        body = json.dumps(SampleResponses.gemini_envelope(SampleResponses.ACCEPTED)).encode()
        with self.reply_with(body) as urlopen:
            self.assertEqual(self.client.generate("prompt", "gemini-x"), SampleResponses.ACCEPTED)
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/gemini-x:generateContent"))
        self.assertNotIn("test-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertEqual(json.loads(request.data)["generationConfig"]["temperature"], 0.0)

    def test_unusable_envelopes_raise_response_errors(self):
        for label, body in {
            "safety blocked": {"promptFeedback": {"blockReason": "SAFETY"}},
            "no parts": {"candidates": [{"content": {"parts": []}}]},
            "empty text": SampleResponses.gemini_envelope("  "),
            "candidate not an object": {"candidates": ["oops"]},
        }.items():
            with self.subTest(label), self.reply_with(json.dumps(body).encode()), self.assertRaises(AIResponseError):
                self.client.generate("prompt", "model")
        for body in (b"<html>502 Bad Gateway</html>", b"[1, 2, 3]"):
            with self.reply_with(body), self.assertRaises(AIResponseError):
                self.client.generate("prompt", "model")

    def test_http_status_maps_to_retry_policy(self):
        for status, expected in {401: AIAuthenticationError, 403: AIAuthenticationError, 400: AIRequestRejectedError,
                                 404: AIRequestRejectedError, 429: AIConnectionError, 503: AIConnectionError}.items():
            error = urllib.error.HTTPError("url", status, "reason", {}, io.BytesIO(b"details"))
            with self.subTest(status=status), self.raise_with(error), self.assertRaises(expected):
                self.client.generate("prompt", "model")

    def test_network_failures_are_connection_errors(self):
        for error in (urllib.error.URLError("refused"), TimeoutError("timed out")):
            with self.subTest(error=error), self.raise_with(error), self.assertRaises(AIConnectionError):
                self.client.generate("prompt", "model")

    def test_real_refused_socket_is_handled(self):
        client = GeminiClient("test-key", base_url="http://127.0.0.1:9/v1beta/models", timeout_seconds=3)
        with self.assertRaises((AIConnectionError, AIResponseError)):
            client.generate("prompt", "model")


if __name__ == "__main__":
    unittest.main()
