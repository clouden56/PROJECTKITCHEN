import unittest
from datetime import date

from src.ai_manager import RecipeAIManager
from src.logic_manager import (
    AllergenChecker, BusinessRule, CookTimeRule, ExpiryScorer, IngredientMatcher, IngredientMatchRule, LogicManager,
    RejectionRule, WarningRule, WasteEstimator,
)
from src.models import Ingredient, Inventory, Outcome, Recipe, RecipeJob, RecipeRequest, RescuedItem, RuleResult
from tests.sample_ai_responses import SampleResponses, StubAIClient

TODAY = date(2026, 11, 2)


class LogicTestCase(unittest.TestCase):
    """Turns hardcoded AI replies into Recipes through the real parse + validate path."""

    parser = RecipeAIManager(StubAIClient([""]), ("unused",))

    def recipe(self, reply: str) -> Recipe:
        return self.parser.validate_response(self.parser.parse_response(reply))

    def evaluate(self, reply: str, max_time: int = 30, allergies=(), must_have=(), logic: LogicManager | None = None):
        job = RecipeJob(RecipeRequest("Dinner", max_time, allergies, must_have), SampleResponses.inventory(TODAY))
        return (logic or LogicManager()).evaluate(self.recipe(reply), job, TODAY)


class VerdictTests(LogicTestCase):
    def test_accepted_with_exact_scores(self):
        result = self.evaluate(SampleResponses.ACCEPTED, max_time=20, allergies=["nuts"])
        self.assertEqual(result.outcome, Outcome.ACCEPTED)
        self.assertEqual(result.status_code, "OPTIMAL_MATCH")
        self.assertEqual(result.match_ratio, 1.0)
        self.assertEqual(result.expiry_priority_score, 100.0, "Spinach(0d)=40 + Eggs(1d)=30 + Cheddar(2d)=30")
        self.assertEqual(sorted(i.name for i in result.rescued_items), ["Cheddar Cheese", "Eggs", "Spinach"])
        self.assertEqual(result.waste_diverted_grams, 950, "6 pcs x 100 g + 200 g + 150 g")
        self.assertTrue(all(r.passed for r in result.rule_results))

    def test_allergen_rejects_via_synonym(self):
        result = self.evaluate(SampleResponses.DAIRY_ALLERGEN, allergies=["dairy"])
        self.assertEqual((result.outcome, result.status_code), (Outcome.REJECTED, "ALLERGEN_CONTAMINATION"))
        self.assertFalse(result.allergen_safe)

    def test_insufficient_ingredients_rejected(self):
        result = self.evaluate(SampleResponses.INSUFFICIENT, max_time=180)
        self.assertEqual((result.outcome, result.status_code), (Outcome.REJECTED, "INSUFFICIENT_INGREDIENTS"))
        self.assertLess(result.match_ratio, 0.5)

    def test_over_time_flagged(self):
        result = self.evaluate(SampleResponses.OVER_TIME, max_time=30)
        self.assertEqual((result.outcome, result.status_code), (Outcome.FLAGGED, "EXCEEDS_TIME_LIMIT"))
        self.assertFalse(result.is_within_time)

    def test_missing_some_flagged(self):
        result = self.evaluate(SampleResponses.MISSING_SOME)
        self.assertEqual((result.outcome, result.status_code), (Outcome.FLAGGED, "MISSING_SOME_INGREDIENTS"))
        self.assertEqual(result.match_ratio, 0.6)
        self.assertEqual(result.missing_ingredients, ("Maple Syrup", "Cinnamon"))

    def test_missing_must_have_flagged(self):
        result = self.evaluate(SampleResponses.ACCEPTED, must_have=["Chicken Breast"])
        self.assertEqual((result.outcome, result.status_code), (Outcome.FLAGGED, "MISSING_MANDATORY_INGREDIENT"))
        self.assertEqual(result.missing_mandatory, ("Chicken Breast",))

    def test_every_rule_is_reported_even_after_the_deciding_failure(self):
        result = self.evaluate(SampleResponses.DAIRY_ALLERGEN, max_time=10, allergies=["dairy"])
        names = [r.rule_name for r in result.rule_results]
        self.assertEqual(names, ["Allergen safety", "Ingredient match", "Must-have ingredients",
                                 "Cooking time", "Shopping needed"])
        failed = [r.rule_name for r in result.rule_results if not r.passed]
        self.assertEqual(failed, ["Allergen safety", "Cooking time", "Shopping needed"])
        self.assertEqual(result.status_code, "ALLERGEN_CONTAMINATION", "First failing rule decides")


class RuleDesignTests(LogicTestCase):
    def test_rule_order_decides_between_simultaneous_failures(self):
        rejected = self.evaluate(SampleResponses.INSUFFICIENT, max_time=10)
        self.assertEqual(rejected.status_code, "INSUFFICIENT_INGREDIENTS", "Insufficient outranks over-time")

    def test_new_rule_plugs_in_without_changing_logic_manager(self):
        class NoDeepFryingRule(WarningRule):
            name = "No deep frying"
            status_code = "DEEP_FRIED"

            def _find_problem(self, facts):
                return "Uses a deep fryer." if "Deep Fryer" in facts.recipe.required_tools else None

        recipe_reply = SampleResponses.ACCEPTED.replace("Non-stick Skillet", "Deep Fryer")
        rules = (*LogicManager.default_rules(), NoDeepFryingRule())
        result = self.evaluate(recipe_reply, max_time=20, logic=LogicManager(rules))
        self.assertEqual((result.outcome, result.status_code), (Outcome.FLAGGED, "DEEP_FRIED"))

    def test_configurable_match_threshold(self):
        strict = LogicManager(LogicManager.default_rules(min_match_ratio=0.8))
        self.assertEqual(self.evaluate(SampleResponses.MISSING_SOME, logic=strict).status_code,
                         "INSUFFICIENT_INGREDIENTS", "60% fails an 80% threshold")
        with self.assertRaises(ValueError):
            IngredientMatchRule(1.5)

    def test_every_rule_is_substitutable_for_business_rule(self):
        logic = LogicManager()
        facts = logic.gather_facts(self.recipe(SampleResponses.OVER_TIME),
                                   RecipeJob(RecipeRequest("Dinner", 30), SampleResponses.inventory(TODAY)))
        for rule in logic.rules:
            with self.subTest(rule=rule.name):
                self.assertIsInstance(rule, BusinessRule)
                result = rule.check(facts)
                self.assertIsInstance(result, RuleResult)
                self.assertTrue(result.message)
                if not result.passed:
                    self.assertEqual(result.outcome, rule.outcome)
                    expected = Outcome.REJECTED if isinstance(rule, RejectionRule) else Outcome.FLAGGED
                    self.assertEqual(rule.outcome, expected)
        self.assertFalse(CookTimeRule().check(facts).passed)


class HelperTests(unittest.TestCase):
    def test_ingredient_matching(self):
        matcher = IngredientMatcher()
        self.assertTrue(matcher.matches("2 large eggs", "Eggs"))
        self.assertTrue(matcher.matches("Tomatoes", "tomato"))
        self.assertFalse(matcher.matches("Chicken Breast", "Bread"))
        self.assertFalse(matcher.matches("", "Bread"))

    def test_staples_do_not_lower_ratio_but_are_still_reported(self):
        recipe = Recipe("Eggy Bread", "Snack", 5, ["Eggs", "Bread"], ["Salt", "Black Pepper"], ["Fry."])
        result = IngredientMatcher().match(recipe, Inventory([Ingredient("Eggs", 2, "pcs", None),
                                                              Ingredient("Bread", 2, "slices", None)]))
        self.assertEqual(result.ratio, 1.0)
        self.assertIn("Salt", result.missing)

    def test_allergen_synonyms_and_plurals(self):
        recipe = Recipe("Garlic Prawns", "Dinner", 10, ["Garlic Prawns"], ["Peanuts"], ["Cook."])
        hits = AllergenChecker().find(recipe, ["shellfish", "nuts", " "])
        self.assertEqual(len(hits), 2)
        self.assertEqual(AllergenChecker().find(recipe, []), [])

    def test_expiry_points_and_waste_units(self):
        self.assertEqual([ExpiryScorer.points(d) for d in (-2, 0, 1, 3, 4, 7, 8)], [40, 40, 30, 30, 15, 15, 5])
        grams = WasteEstimator().estimate([
            RescuedItem("Chicken", 1, 0.5, "kg"), RescuedItem("Milk", 2, 250, "ml"),
            RescuedItem("Eggs", 0, None, "pcs"), RescuedItem("Rice", 6, 999, "g"),
        ])
        self.assertEqual(grams, 500 + 250 + 100, "kg->g, ml~g, unknown qty = 1 unit, >3 days ignored")

    def test_score_is_capped_and_ignores_unused_items(self):
        inventory = Inventory([Ingredient(n, 1, "pcs", TODAY) for n in ("Eggs", "Milk", "Spinach")])
        recipe = Recipe("Everything", "Dinner", 10, ["Eggs", "Milk", "Spinach", "Bacon"], [], ["Cook."])
        self.assertEqual(ExpiryScorer().score(recipe, inventory, TODAY), 100.0)
        self.assertEqual(ExpiryScorer().score(Recipe("None", "Dinner", 5, ["Bacon"], [], ["Cook."]), inventory, TODAY), 0.0)


if __name__ == "__main__":
    unittest.main()
