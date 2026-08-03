"""Load configuration from config.yaml and secrets from the environment (.env)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Folder the user interacts with.

    - Running as a normal script: the project root.
    - Running as a PyInstaller .exe: the folder that contains the .exe, so
      config.yaml, .env, and log.txt sit next to the app and stay editable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def resource_dir() -> Path:
    """Folder holding bundled read-only defaults (config.yaml shipped inside the exe)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return PROJECT_ROOT


def log_file_path() -> Path:
    return app_dir() / "log.txt"


def _default_config_path() -> Path:
    """Prefer an editable config.yaml next to the app; fall back to the bundled one."""
    beside = app_dir() / "config.yaml"
    if beside.exists():
        return beside
    return resource_dir() / "config.yaml"


DEFAULT_CONFIG_PATH = _default_config_path()

# Image extensions we will pick up when a folder is given.
SUPPORTED_INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}


@dataclass
class Secrets:
    topaz_api_key: str
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key.strip())


@dataclass
class Config:
    settings: dict[str, Any] = field(default_factory=dict)
    secrets: Secrets | None = None

    def __getitem__(self, key: str) -> Any:
        return self.settings[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


def load_secrets() -> Secrets:
    """Read secrets from the environment / .env file."""
    load_dotenv(app_dir() / ".env")
    topaz = os.getenv("TOPAZ_API_KEY", "").strip()
    if not topaz:
        raise RuntimeError(
            "TOPAZ_API_KEY is not set. Open the .env file next to the app and add "
            "your Topaz Labs API key (copy .env.example if .env is missing)."
        )
    return Secrets(
        topaz_api_key=topaz,
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").strip(),
        llm_model=os.getenv("LLM_MODEL", "openai/gpt-4o-mini").strip(),
    )


def load_config(config_path: str | Path | None = None, *, load_env: bool = True) -> Config:
    path = Path(config_path) if config_path else _default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        settings = yaml.safe_load(fh) or {}
    secrets = load_secrets() if load_env else None
    return Config(settings=settings, secrets=secrets)
