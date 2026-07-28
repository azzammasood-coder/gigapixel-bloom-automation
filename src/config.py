"""Load configuration from config.yaml and secrets from the environment (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

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
    load_dotenv(PROJECT_ROOT / ".env")
    topaz = os.getenv("TOPAZ_API_KEY", "").strip()
    if not topaz:
        raise RuntimeError(
            "TOPAZ_API_KEY is not set. Copy .env.example to .env and add your "
            "Topaz Labs API key."
        )
    return Secrets(
        topaz_api_key=topaz,
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").strip(),
        llm_model=os.getenv("LLM_MODEL", "openai/gpt-4o-mini").strip(),
    )


def load_config(config_path: str | Path | None = None, *, load_env: bool = True) -> Config:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        settings = yaml.safe_load(fh) or {}
    secrets = load_secrets() if load_env else None
    return Config(settings=settings, secrets=secrets)
