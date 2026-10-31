"""Application settings, read from environment variables and an optional, git-ignored .env file."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Mapping

logger = logging.getLogger(__name__)


class EnvironmentFile:
    """Reads KEY=VALUE lines from a .env file. Real environment variables always take precedence."""

    def __init__(self, path: str = ".env") -> None:
        self._path = path

    def read(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if not os.path.exists(self._path):
            return values
        try:
            with open(self._path, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip():
                        values[key.strip()] = value.strip().strip("'\"")
        except (OSError, UnicodeDecodeError) as err:
            logger.error("Could not read %s: %s", self._path, err)
        return values


class AppConfig:
    """Every setting the application needs, resolved once at start-up."""

    DEFAULT_MODELS = ("gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash-lite")

    def __init__(self, api_key: str = "", data_dir: str = "data", host: str = "127.0.0.1", port: int = 5000,
                 models: tuple[str, ...] = DEFAULT_MODELS, secret_key: str = "") -> None:
        self._api_key = api_key
        self._data_dir = data_dir
        self._host = host
        self._port = port
        self._models = models
        self._secret_key = secret_key or secrets.token_hex(16)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, env_file: str = ".env") -> AppConfig:
        values = {**EnvironmentFile(env_file).read(), **(os.environ if environ is None else environ)}
        models = tuple(m.strip() for m in values.get("GEMINI_MODELS", "").split(",") if m.strip())
        try:
            port = int(values.get("PORT", "5000"))
        except ValueError:
            logger.warning("Invalid PORT %r; using 5000.", values.get("PORT"))
            port = 5000
        return cls(
            api_key=values.get("GEMINI_API_KEY", "").strip(),
            data_dir=values.get("DATA_DIR", "data"),
            host=values.get("HOST", "127.0.0.1"),
            port=port,
            models=models or cls.DEFAULT_MODELS,
            secret_key=values.get("SECRET_KEY", ""),
        )

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def models(self) -> tuple[str, ...]:
        return self._models

    @property
    def secret_key(self) -> str:
        return self._secret_key

    @property
    def inventory_path(self) -> str:
        return os.path.join(self._data_dir, "inventory.json")

    @property
    def history_path(self) -> str:
        return os.path.join(self._data_dir, "recipe_history.json")

    @property
    def log_path(self) -> str:
        return os.path.join(self._data_dir, "app.log")
