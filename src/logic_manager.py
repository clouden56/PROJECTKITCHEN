"""
Logic Manager - domain rules.

Judges a validated AI recipe against the user's request and inventory: gathers the facts once
(ingredient match, allergens, must-haves, cook time), runs every BusinessRule to explain the verdict,
routes the recipe to ACCEPTED / FLAGGED / REJECTED, and scores how much near-expiry food it rescues.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from src.models import (
    Evaluation, Ingredient, Inventory, Outcome, Recipe, RecipeJob, RecipeRequest, RescuedItem, RuleResult,
)


class IngredientMatcher:
    """Decides whether two ingredient descriptions refer to the same food ("2 large eggs" vs "Eggs")."""

    STOPWORDS = frozenset({"tsp", "tbsp", "cup", "cups", "g", "kg", "ml", "pcs", "pinch", "pinches", "of", "fresh",
                           "diced", "shredded", "sliced", "chopped", "a", "an", "the", "or", "and"})
    PANTRY_STAPLES = ("salt", "pepper", "black pepper", "water", "cooking oil", "oil", "butter")

    def __init__(self) -> None:
        self._staple_words = frozenset().union(*(self.normalise(s) for s in self.PANTRY_STAPLES))

    def normalise(self, text: str) -> set[str]:
        """Lower-cased words without quantities, units or filler words, plus their singular forms."""
        words = set()
        for raw in text.lower().replace("-", " ").replace(",", " ").split():
            word = "".join(c for c in raw if c.isalpha())
            if not word or word in self.STOPWORDS:
                continue
            words.add(word)
            if word.endswith("es") and len(word) > 4:
                words.add(word[:-2])
            elif word.endswith("s") and len(word) > 3:
                words.add(word[:-1])
        return words

    def matches(self, first: str, second: str) -> bool:
        a, b = first.strip().lower(), second.strip().lower()
        if not a or not b:
            return False
        if a in b or b in a:
            return True
        return bool(self.normalise(a) & self.normalise(b))

    def is_staple(self, text: str) -> bool:
        words = self.normalise(text)
        return bool(words) and words <= self._staple_words

    def match(self, recipe: Recipe, inventory: Inventory) -> MatchResult:
        """How much of the recipe the user already owns. Pantry staples never lower the ratio."""
        names = [item.name for item in inventory]
        matched = [used for used in recipe.ingredients_used if any(self.matches(used, n) for n in names)]
        not_owned = [used for used in recipe.ingredients_used if used not in matched]
        critical_missing = not_owned + [m for m in recipe.missing_ingredients if not self.is_staple(m)]
        total = len(matched) + len(critical_missing)
        ratio = round(len(matched) / total, 2) if total else (1.0 if matched else 0.0)
        reported_missing = list(dict.fromkeys(not_owned + list(recipe.missing_ingredients)))
        return MatchResult(ratio, matched, reported_missing)


class MatchResult:
    def __init__(self, ratio: float, matched: Iterable[str], missing: Iterable[str]) -> None:
        self._ratio = ratio
        self._matched = tuple(matched)
        self._missing = tuple(missing)

    @property
    def ratio(self) -> float:
        return self._ratio

    @property
    def matched(self) -> tuple[str, ...]:
        return self._matched

    @property
    def missing(self) -> tuple[str, ...]:
        return self._missing


class AllergenChecker:
    """Finds the user's allergens in a recipe, including common synonyms (dairy -> cheese, milk ...)."""

    SYNONYMS = {
        "dairy": ("milk", "cheese", "butter", "cream", "yogurt", "ghee"),
        "nuts": ("peanut", "almond", "walnut", "cashew", "pistachio", "pecan", "hazelnut"),
        "gluten": ("flour", "bread", "pasta", "wheat", "barley", "rye"),
        "egg": ("egg", "mayonnaise"),
        "shellfish": ("shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster"),
        "soy": ("soy", "soya", "tofu", "edamame"),
    }

    @staticmethod
    def _stem(word: str) -> str:
        return word[:-1] if word.endswith("s") and len(word) > 3 else word

    def find(self, recipe: Recipe, allergies: Iterable[str]) -> list[str]:
        ingredients = [i.lower() for i in recipe.all_ingredients()]
        hits = []
        for allergen in (a.strip().lower() for a in allergies if a.strip()):
            stem = self._stem(allergen)
            synonyms = self.SYNONYMS.get(allergen) or self.SYNONYMS.get(stem) or ()
            for ingredient in ingredients:
                if allergen in ingredient or stem in ingredient:
                    hits.append(f"{allergen} found in '{ingredient}'")
                    continue
                synonym = next((s for s in synonyms if s in ingredient or self._stem(s) in ingredient), None)
                if synonym:
                    hits.append(f"{allergen} ({synonym}) found in '{ingredient}'")
        return list(dict.fromkeys(hits))


class ExpiryScorer:
    """Scores how urgently a recipe uses up the inventory: the sooner an ingredient expires, the more it counts."""

    MAX_SCORE = 100.0
    RESCUE_WINDOW_DAYS = 7

    def used_items(self, recipe: Recipe, inventory: Inventory) -> list[Ingredient]:
        used = [u.strip().lower() for u in recipe.ingredients_used]
        return [item for item in inventory
                if any(item.name.lower() in u or u in item.name.lower() for u in used if u)]

    @staticmethod
    def points(days_until_expiry: int) -> int:
        if days_until_expiry <= 0:
            return 40
        if days_until_expiry <= 3:
            return 30
        if days_until_expiry <= 7:
            return 15
        return 5

    def score(self, recipe: Recipe, inventory: Inventory, today: date) -> float:
        total = sum(self.points(i.days_until_expiry(today)) for i in self.used_items(recipe, inventory))
        return min(self.MAX_SCORE, float(total))

    def rescued_items(self, recipe: Recipe, inventory: Inventory, today: date) -> list[RescuedItem]:
        return [RescuedItem(i.name, i.days_until_expiry(today), i.quantity, i.unit)
                for i in self.used_items(recipe, inventory)
                if i.days_until_expiry(today) <= self.RESCUE_WINDOW_DAYS]


class WasteEstimator:
    """Estimates the grams of food a recipe saves from the bin (items within 3 days of expiry)."""

    URGENT_DAYS = 3
    GRAMS_PER_UNIT = {"g": 1, "grams": 1, "kg": 1000, "kilograms": 1000, "ml": 1, "milliliters": 1}
    DEFAULT_GRAMS_PER_ITEM = 100

    def estimate(self, rescued: Iterable[RescuedItem]) -> int:
        total = 0
        for item in rescued:
            if item.days_until_expiry > self.URGENT_DAYS:
                continue
            try:
                quantity = float(item.quantity)
            except (TypeError, ValueError):
                quantity = 1.0
            total += int(quantity * self.GRAMS_PER_UNIT.get(item.unit.lower(), self.DEFAULT_GRAMS_PER_ITEM))
        return total


class EvaluationFacts:
    """Everything the rules need about one recipe, computed once and shared by every rule."""

    def __init__(self, recipe: Recipe, request: RecipeRequest, match: MatchResult,
                 allergen_hits: Iterable[str], missing_mandatory: Iterable[str]) -> None:
        self._recipe = recipe
        self._request = request
        self._match = match
        self._allergen_hits = tuple(allergen_hits)
        self._missing_mandatory = tuple(missing_mandatory)

    @property
    def recipe(self) -> Recipe:
        return self._recipe

    @property
    def request(self) -> RecipeRequest:
        return self._request

    @property
    def match(self) -> MatchResult:
        return self._match

    @property
    def allergen_hits(self) -> tuple[str, ...]:
        return self._allergen_hits

    @property
    def missing_mandatory(self) -> tuple[str, ...]:
        return self._missing_mandatory

    @property
    def within_time(self) -> bool:
        return self._recipe.cook_time_mins <= self._request.max_cook_time_mins


class BusinessRule(ABC):
    """
    One domain rule. check() is shared: it turns the subclass's finding into a RuleResult, so the
    LogicManager can run any rule the same way without knowing which rule it is.
    """

    name = "Rule"
    status_code = "RULE_FAILED"

    @property
    @abstractmethod
    def outcome(self) -> Outcome:
        """The outcome this rule forces when it fails."""

    def check(self, facts: EvaluationFacts) -> RuleResult:
        problem = self._find_problem(facts)
        if problem is None:
            return RuleResult(self.name, True, message=self._describe_pass(facts))
        return RuleResult(self.name, False, self.outcome, self.status_code, problem)

    @abstractmethod
    def _find_problem(self, facts: EvaluationFacts) -> str | None:
        """Returns a message describing the violation, or None if the recipe passes."""

    def _describe_pass(self, facts: EvaluationFacts) -> str:
        return "Passed."


class RejectionRule(BusinessRule, ABC):
    """A rule whose failure makes the recipe unsuitable."""

    @property
    def outcome(self) -> Outcome:
        return Outcome.REJECTED


class WarningRule(BusinessRule, ABC):
    """A rule whose failure still allows the recipe but flags it for the user's attention."""

    @property
    def outcome(self) -> Outcome:
        return Outcome.FLAGGED


class AllergenRule(RejectionRule):
    name = "Allergen safety"
    status_code = "ALLERGEN_CONTAMINATION"

    def _find_problem(self, facts: EvaluationFacts) -> str | None:
        if not facts.allergen_hits:
            return None
        return f"Recipe rejected due to detected allergens: {', '.join(facts.allergen_hits)}."

    def _describe_pass(self, facts: EvaluationFacts) -> str:
        if not facts.request.allergies:
            return "No allergies declared."
        return f"None of your allergens ({', '.join(facts.request.allergies)}) appear in the recipe."


class IngredientMatchRule(RejectionRule):
    name = "Ingredient match"
    status_code = "INSUFFICIENT_INGREDIENTS"

    def __init__(self, min_ratio: float = 0.5) -> None:
        if not 0 <= min_ratio <= 1:
            raise ValueError("Minimum match ratio must be between 0 and 1.")
        self._min_ratio = min_ratio

    @property
    def min_ratio(self) -> float:
        return self._min_ratio

    def _find_problem(self, facts: EvaluationFacts) -> str | None:
        if facts.match.ratio >= self._min_ratio:
            return None
        return (f"Ingredient match ratio ({int(facts.match.ratio * 100)}%) is below the minimum threshold of "
                f"{int(self._min_ratio * 100)}%.")

    def _describe_pass(self, facts: EvaluationFacts) -> str:
        return f"{int(facts.match.ratio * 100)}% of the ingredients are in your kitchen (minimum {int(self._min_ratio * 100)}%)."


class MandatoryIngredientRule(WarningRule):
    name = "Must-have ingredients"
    status_code = "MISSING_MANDATORY_INGREDIENT"

    def _find_problem(self, facts: EvaluationFacts) -> str | None:
        if not facts.missing_mandatory:
            return None
        return ("Recipe generated but missing your requested mandatory ingredient(s): "
                f"{', '.join(facts.missing_mandatory)}.")

    def _describe_pass(self, facts: EvaluationFacts) -> str:
        if not facts.request.mandatory_ingredients:
            return "No must-have ingredients requested."
        return f"Includes {', '.join(facts.request.mandatory_ingredients)}."


class CookTimeRule(WarningRule):
    name = "Cooking time"
    status_code = "EXCEEDS_TIME_LIMIT"

    def _find_problem(self, facts: EvaluationFacts) -> str | None:
        if facts.within_time:
            return None
        return (f"Recipe cook time ({facts.recipe.cook_time_mins} mins) exceeds your limit of "
                f"{facts.request.max_cook_time_mins} mins.")

    def _describe_pass(self, facts: EvaluationFacts) -> str:
        return f"{facts.recipe.cook_time_mins} mins fits your {facts.request.max_cook_time_mins}-minute limit."


class MissingIngredientRule(WarningRule):
    name = "Shopping needed"
    status_code = "MISSING_SOME_INGREDIENTS"

    def _find_problem(self, facts: EvaluationFacts) -> str | None:
        if not facts.match.missing:
            return None
        return (f"Recipe approved with caution ({int(facts.match.ratio * 100)}% match). "
                f"Missing items: {', '.join(facts.match.missing)}.")

    def _describe_pass(self, facts: EvaluationFacts) -> str:
        return "You have everything the recipe needs."


class Verdict:
    """The routed outcome plus the result of every rule that was checked."""

    ACCEPTED_CODE = "OPTIMAL_MATCH"
    ACCEPTED_MESSAGE = "Recipe perfectly matches your fridge ingredients and cooking parameters!"

    def __init__(self, outcome: Outcome, status_code: str, message: str, rule_results: Iterable[RuleResult]) -> None:
        self._outcome = outcome
        self._status_code = status_code
        self._message = message
        self._rule_results = tuple(rule_results)

    @property
    def outcome(self) -> Outcome:
        return self._outcome

    @property
    def status_code(self) -> str:
        return self._status_code

    @property
    def message(self) -> str:
        return self._message

    @property
    def rule_results(self) -> tuple[RuleResult, ...]:
        return self._rule_results


class LogicManager:
    """
    Evaluates AI recipes. Aggregates an ordered list of BusinessRules: the first failing rule decides the
    outcome. New rules can be added without changing this class.
    """

    def __init__(self, rules: Iterable[BusinessRule] | None = None, matcher: IngredientMatcher | None = None,
                 allergen_checker: AllergenChecker | None = None, scorer: ExpiryScorer | None = None,
                 waste_estimator: WasteEstimator | None = None) -> None:
        self._rules = tuple(rules) if rules is not None else self.default_rules()
        self._matcher = matcher or IngredientMatcher()
        self._allergen_checker = allergen_checker or AllergenChecker()
        self._scorer = scorer or ExpiryScorer()
        self._waste_estimator = waste_estimator or WasteEstimator()

    @staticmethod
    def default_rules(min_match_ratio: float = 0.5) -> tuple[BusinessRule, ...]:
        """Phase 1 rule order: safety first, then ingredients, must-haves, time and shopping."""
        return (AllergenRule(), IngredientMatchRule(min_match_ratio), MandatoryIngredientRule(),
                CookTimeRule(), MissingIngredientRule())

    @property
    def rules(self) -> tuple[BusinessRule, ...]:
        return self._rules

    def evaluate(self, recipe: Recipe, job: RecipeJob, today: date) -> Evaluation:
        facts = self.gather_facts(recipe, job)
        verdict = self.route(facts)
        rescued = self._scorer.rescued_items(recipe, job.inventory, today)
        return Evaluation(
            outcome=verdict.outcome,
            status_code=verdict.status_code,
            status_message=verdict.message,
            match_ratio=facts.match.ratio,
            matched_ingredients=facts.match.matched,
            missing_ingredients=facts.match.missing,
            missing_mandatory=facts.missing_mandatory,
            expiry_priority_score=self.score(recipe, job.inventory, today),
            rescued_items=rescued,
            waste_diverted_grams=self._waste_estimator.estimate(rescued),
            allergen_safe=not facts.allergen_hits,
            is_within_time=facts.within_time,
            rule_results=verdict.rule_results,
        )

    def gather_facts(self, recipe: Recipe, job: RecipeJob) -> EvaluationFacts:
        request = job.request
        missing_mandatory = [m for m in request.mandatory_ingredients
                             if not any(self._matcher.matches(m, used) for used in recipe.ingredients_used)]
        return EvaluationFacts(
            recipe=recipe,
            request=request,
            match=self._matcher.match(recipe, job.inventory),
            allergen_hits=self._allergen_checker.find(recipe, request.allergies),
            missing_mandatory=missing_mandatory,
        )

    def score(self, recipe: Recipe, inventory: Inventory, today: date) -> float:
        return self._scorer.score(recipe, inventory, today)

    def route(self, facts: EvaluationFacts) -> Verdict:
        results = [rule.check(facts) for rule in self._rules]
        deciding = next((result for result in results if not result.passed), None)
        if deciding is None:
            return Verdict(Outcome.ACCEPTED, Verdict.ACCEPTED_CODE, Verdict.ACCEPTED_MESSAGE, results)
        return Verdict(deciding.outcome, deciding.status_code, deciding.message, results)
