"""
Entry point. Application is the composition root: it creates the configuration, the four managers, the
KitchenService and the web interface, and owns them for the life of the process.
"""

from __future__ import annotations

import logging
import os
import sys

from src.ai_manager import GeminiClient, RecipeAIManager
from src.config import AppConfig
from src.data_manager import DataManager
from src.io_manager import IOManager
from src.kitchen_service import KitchenService
from src.logic_manager import LogicManager
from src.web_app import WebApp


class Application:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._configure_logging()
        data_manager = DataManager(config.inventory_path, config.history_path)
        ai_manager = RecipeAIManager(GeminiClient(config.api_key), config.models)
        self._service = KitchenService(data_manager, ai_manager, LogicManager())
        self._web = WebApp(self._service, IOManager(), config.secret_key)
        if not config.api_key:
            logging.getLogger(__name__).warning("GEMINI_API_KEY is not set: recipe suggestions will fail.")

    @classmethod
    def from_environment(cls) -> Application:
        return cls(AppConfig.from_environment())

    @property
    def web(self) -> WebApp:
        return self._web

    def run(self) -> None:
        self._web.run(self._config.host, self._config.port)

    def _configure_logging(self) -> None:
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
        try:
            os.makedirs(os.path.dirname(self._config.log_path) or ".", exist_ok=True)
            handlers.append(logging.FileHandler(self._config.log_path, encoding="utf-8"))
        except OSError:
            pass
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                            handlers=handlers)


if __name__ == "__main__":
    Application.from_environment().run()
