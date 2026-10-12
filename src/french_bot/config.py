"""Explicit environment configuration; paths are relative to the working directory."""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    pass


def boolean(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ConfigurationError(f"{name} must be true or false.")
    return value in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "gpt-4.1-mini"
    timezone: str = "Europe/London"
    output_dir: Path = Path("output")
    database_path: Path = Path("data/stories.sqlite3")
    publish_mode: str = "local"
    editor_review: bool = True
    include_cta: bool = True
    timeout: float = 90
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False)
        try:
            settings = cls(
                api_key=os.getenv("OPENAI_API_KEY", "").strip(),
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
                timezone=os.getenv("TZ", "Europe/London").strip(),
                output_dir=Path(os.getenv("OUTPUT_DIR", "./output")).resolve(),
                database_path=Path(os.getenv("DATABASE_PATH", "./data/stories.sqlite3")).resolve(),
                publish_mode=os.getenv("PUBLISH_MODE", "local").strip(),
                editor_review=boolean("EDITOR_REVIEW", True),
                include_cta=boolean("INCLUDE_CTA", True),
                timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "90")),
                max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
            )
            ZoneInfo(settings.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ConfigurationError(
                "Invalid configuration: check TZ, booleans and numeric settings."
            ) from exc
        if not settings.model or settings.timeout <= 0 or not 0 <= settings.max_retries <= 5:
            raise ConfigurationError("Set a model, a positive timeout, and 0–5 API retries.")
        if settings.publish_mode != "local":
            raise ConfigurationError("Only PUBLISH_MODE=local is implemented in v1.")
        return settings

    def today(self):
        return datetime.now(ZoneInfo(self.timezone)).date()
