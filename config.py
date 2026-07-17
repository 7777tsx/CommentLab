from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")
DEFAULT_PROMPT_VERSION = "2026-07-18.1"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.4
    timeout: int = 30
    demo_mode: bool = True
    database_path: Path = ROOT_DIR / "commentlab.db"
    web_search_enabled: bool = True
    web_search_model: str = ""
    prompt_version: str = DEFAULT_PROMPT_VERSION

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("LLM_API_KEY", "").strip()
        base_url = os.getenv("LLM_BASE_URL", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()
        requested_demo = _as_bool(os.getenv("DEMO_MODE"), default=True)
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.4")),
            timeout=int(os.getenv("LLM_TIMEOUT", "30")),
            demo_mode=requested_demo or not all((api_key, base_url, model)),
            database_path=Path(os.getenv("DATABASE_PATH", str(ROOT_DIR / "commentlab.db"))),
            web_search_enabled=_as_bool(
                os.getenv("WEB_SEARCH_ENABLED"), default=True
            ),
            web_search_model=os.getenv("WEB_SEARCH_MODEL", "").strip() or model,
            prompt_version=(
                os.getenv("PROMPT_VERSION", DEFAULT_PROMPT_VERSION).strip()
                or DEFAULT_PROMPT_VERSION
            ),
        )

    @property
    def live_ready(self) -> bool:
        return not self.demo_mode and all((self.api_key, self.base_url, self.model))


settings = Settings.from_env()
