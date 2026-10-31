"""
Hardcoded sample AI replies and a scripted AI client, so every test runs without a live API.
Each recipe sample is designed to land on one specific ACCEPTED / FLAGGED / REJECTED branch.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Iterable

from src.ai_manager import AIClient
from src.models import Ingredient, Inventory


class SampleResponses:
    ACCEPTED = json.dumps({
        "recipe_name": "Spinach & Cheddar Omelette",
        "meal_type": "Breakfast",
        "estimated_cook_time_mins": 15,
        "required_tools": ["Non-stick Skillet", "Whisk", "Spatula"],
        "ingredients_used": ["3 Eggs", "50g Cheddar Cheese, shredded", "1 cup fresh Spinach"],
        "missing_ingredients": [],
        "instructions": ["Whisk the eggs.", "Wilt the spinach.", "Add eggs and cook until set.",
                         "Add cheddar, fold and serve."],
        "waste_reduction_notes": "Uses spinach expiring today plus eggs and cheddar expiring within 2 days.",
    })

    DAIRY_ALLERGEN = json.dumps({
        "recipe_name": "Creamy Chicken Alfredo",
        "meal_type": "Dinner",
        "estimated_cook_time_mins": 25,
        "required_tools": ["Large Pot", "Skillet"],
        "ingredients_used": ["Chicken Breast", "Milk", "Cheddar Cheese"],
        "missing_ingredients": ["Fettuccine pasta", "Butter"],
        "instructions": ["Boil pasta.", "Sear chicken.", "Make the sauce.", "Combine."],
        "waste_reduction_notes": "Uses milk before it expires.",
    })

    INSUFFICIENT = json.dumps({
        "recipe_name": "Beef Rendang",
        "meal_type": "Dinner",
        "estimated_cook_time_mins": 120,
        "required_tools": ["Dutch Oven"],
        "ingredients_used": ["Beef Chuck", "Coconut Cream", "Lemongrass", "Spinach"],
        "missing_ingredients": ["Galangal", "Kaffir Lime Leaves", "Chilli Paste"],
        "instructions": ["Pound the spice paste.", "Brown the beef.", "Simmer for 2 hours."],
        "waste_reduction_notes": "Adds spinach as a side.",
    })

    OVER_TIME = json.dumps({
        "recipe_name": "Baked Chicken with Spinach",
        "meal_type": "Dinner",
        "estimated_cook_time_mins": 50,
        "required_tools": ["Oven", "Baking Tray"],
        "ingredients_used": ["Chicken Breast", "Spinach"],
        "missing_ingredients": [],
        "instructions": ["Preheat oven.", "Bake chicken for 40 minutes.", "Serve on wilted spinach."],
        "waste_reduction_notes": "Rescues spinach expiring today.",
    })

    MISSING_SOME = json.dumps({
        "recipe_name": "French Toast",
        "meal_type": "Breakfast",
        "estimated_cook_time_mins": 15,
        "required_tools": ["Skillet", "Shallow Dish"],
        "ingredients_used": ["Bread", "Eggs", "Milk"],
        "missing_ingredients": ["Maple Syrup", "Cinnamon"],
        "instructions": ["Whisk eggs and milk.", "Soak bread.", "Fry until golden."],
        "waste_reduction_notes": "Uses milk and eggs close to expiry.",
    })

    FENCED = "```json\n" + json.dumps({
        "recipe_name": "Cheese Toast",
        "meal_type": "Snack",
        "estimated_cook_time_mins": 5,
        "required_tools": [],
        "ingredients_used": ["Bread", "Cheddar Cheese"],
        "missing_ingredients": [],
        "instructions": ["Top bread with cheese.", "Toast until melted."],
        "waste_reduction_notes": "Uses cheddar before it expires.",
    }) + "\n```"

    MALFORMED = {
        "prose instead of JSON": "Sure! Whisk 3 eggs, add spinach and cheese, then fry.",
        "truncated JSON": '{"recipe_name": "Spinach Omelette", "meal_type": "Break',
        "top-level array": json.dumps(["Eggs", "Spinach"]),
        "missing instructions": json.dumps({k: v for k, v in json.loads(ACCEPTED).items() if k != "instructions"}),
        "string cook time": json.dumps({**json.loads(ACCEPTED), "estimated_cook_time_mins": "about 10 minutes"}),
        "boolean cook time": json.dumps({**json.loads(ACCEPTED), "estimated_cook_time_mins": True}),
        "negative cook time": json.dumps({**json.loads(ACCEPTED), "estimated_cook_time_mins": -5}),
        "empty ingredients": json.dumps({**json.loads(ACCEPTED), "ingredients_used": []}),
        "blank name": json.dumps({**json.loads(ACCEPTED), "recipe_name": "   "}),
    }

    @staticmethod
    def gemini_envelope(text: str) -> dict:
        """A generateContent HTTP reply wrapping the model's text, exactly as the live API returns it."""
        return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP"}],
                "modelVersion": "gemini-3.6-flash"}

    @staticmethod
    def inventory(today: date) -> Inventory:
        """The inventory the recipe samples were written for; expiry dates are relative to `today`."""
        def on(days: int) -> date:
            return today + timedelta(days=days)

        return Inventory([
            Ingredient("Eggs", 6, "pcs", on(1)),
            Ingredient("Cheddar Cheese", 200, "g", on(2)),
            Ingredient("Spinach", 150, "g", on(0)),
            Ingredient("Bread", 4, "slices", on(10), "Pantry"),
            Ingredient("Chicken Breast", 0.5, "kg", on(5)),
            Ingredient("Milk", 500, "ml", on(3)),
        ])


class StubAIClient(AIClient):
    """
    Scripted stand-in for GeminiClient. Each call returns the next scripted reply, or raises it if it is
    an exception; the last item repeats. Records every (prompt, model) it was called with.
    """

    def __init__(self, replies: Iterable[str | Exception]) -> None:
        self._replies = list(replies)
        self._calls: list[tuple[str, str]] = []

    @property
    def calls(self) -> list[tuple[str, str]]:
        return self._calls

    @property
    def models_called(self) -> list[str]:
        return [model for _, model in self._calls]

    def generate(self, prompt: str, model: str) -> str:
        self._calls.append((prompt, model))
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply
