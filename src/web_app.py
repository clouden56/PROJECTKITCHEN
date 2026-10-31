"""
Web interface (part of the IO layer). Maps HTTP routes to KitchenService use cases: IOManager validates what
the user submits, and Jinja templates display the results. No domain rules live here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for

from src.ai_manager import AIProcessingError
from src.io_manager import IOManager
from src.kitchen_service import (
    IngredientNotFoundError, InsufficientInventoryError, KitchenService, StorageError,
)

logger = logging.getLogger(__name__)


class WebApp:
    """Owns the Flask application and its routes. Associated with the KitchenService and IOManager it is given."""

    RECENT_RECIPES = 5
    DEFAULT_REQUEST = {"meal_type": "Dinner", "max_cook_time_mins": "30"}

    def __init__(self, service: KitchenService, io: IOManager, secret_key: str) -> None:
        here = os.path.dirname(os.path.abspath(__file__))
        self._flask = Flask(__name__, template_folder=os.path.join(here, "templates"),
                            static_folder=os.path.join(here, "static"))
        self._flask.secret_key = secret_key
        self._flask.config["MAX_CONTENT_LENGTH"] = 16 * 1024
        self._service = service
        self._io = io
        self._register_routes()

    @property
    def flask(self) -> Flask:
        return self._flask

    def run(self, host: str, port: int) -> None:
        logger.info("Serving Fridge Recipe Tracker on http://%s:%d", host, port)
        self._flask.run(host=host, port=port, debug=False)

    def _register_routes(self) -> None:
        routes = (
            ("/", "dashboard", self.dashboard, ("GET",)),
            ("/inventory", "inventory", self.inventory, ("GET",)),
            ("/inventory", "add_ingredient", self.add_ingredient, ("POST",)),
            ("/inventory/remove", "remove_ingredient", self.remove_ingredient, ("POST",)),
            ("/recipes/new", "new_recipe", self.new_recipe, ("GET",)),
            ("/recipes", "generate_recipe", self.generate_recipe, ("POST",)),
            ("/history", "history", self.history, ("GET",)),
            ("/health", "health", self.health, ("GET",)),
        )
        for rule, endpoint, view, methods in routes:
            self._flask.add_url_rule(rule, endpoint, view, methods=list(methods))
        self._flask.register_error_handler(404, self.not_found)
        self._flask.context_processor(self._template_globals)

    def _template_globals(self) -> dict[str, Any]:
        return {"io": self._io, "today": self._service.today()}

    def dashboard(self):
        inventory = self._service.inventory()
        return render_template("dashboard.html", inventory=inventory, expiring=self._service.expiring_soon(),
                               recent=self._service.history()[:self.RECENT_RECIPES])

    def inventory(self):
        return self._render_inventory({}, {})

    def add_ingredient(self):
        result = self._io.parse_ingredient(request.form)
        if not result.ok:
            return self._render_inventory(result.submitted, result.errors), 422
        try:
            stored = self._service.add_ingredient(result.value)
        except StorageError as err:
            flash(str(err), "error")
        else:
            flash(f"Saved {stored.name} to your {stored.location.lower()}.", "success")
        return redirect(url_for("inventory"))

    def remove_ingredient(self):
        name = request.form.get("name", "")
        try:
            removed = self._service.remove_ingredient(name)
        except (IngredientNotFoundError, StorageError) as err:
            flash(str(err), "error")
        else:
            flash(f"Removed {removed.name}.", "success")
        return redirect(url_for("inventory"))

    def new_recipe(self):
        return self._render_recipe_form(dict(self.DEFAULT_REQUEST), {})

    def generate_recipe(self):
        result = self._io.parse_recipe_request(request.form)
        if not result.ok:
            return self._render_recipe_form(result.submitted, result.errors), 422
        try:
            record = self._service.generate_recipe(result.value)
        except InsufficientInventoryError as err:
            return self._render_recipe_form(result.submitted, {}, problem=str(err)), 422
        except AIProcessingError as err:
            logger.error("Recipe generation failed: %s", err)
            return self._render_recipe_form(result.submitted, {}, problem=str(err)), 503
        except StorageError as err:
            flash(str(err), "error")
            return render_template("unsaved_recipe.html", record=err.record), 500
        flash(f"Your recipe is ready: {record.recipe.name}.", "success")
        return redirect(url_for("history"))

    def history(self):
        record_filter, selected = self._io.parse_history_filter(request.args)
        return render_template("history.html", records=self._service.history(record_filter), selected=selected,
                               filtered=any(selected.values()))

    def health(self):
        return {"status": "ok"}

    def not_found(self, error):
        return render_template("not_found.html"), 404

    def _render_inventory(self, submitted: dict[str, str], errors: dict[str, str]):
        today = self._service.today()
        expiring_only = request.args.get("view") == "expiring"
        items = self._service.expiring_soon() if expiring_only else sorted(
            self._service.inventory(), key=lambda i: (i.days_until_expiry(today), i.name.lower()))
        return render_template("inventory.html", items=items, form=submitted, errors=errors,
                               expiring_only=expiring_only)

    def _render_recipe_form(self, submitted: dict[str, str], errors: dict[str, str], problem: str = ""):
        return render_template("recipe_form.html", form=submitted, errors=errors, problem=problem,
                               inventory_count=len(self._service.inventory()),
                               minimum=KitchenService.MIN_INGREDIENTS)
