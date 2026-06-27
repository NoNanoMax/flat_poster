"""Settings model — loads config/settings.yaml + .env via pydantic-settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


def _find_config_dir() -> Path:
    """Find config/ relative to project root (flat_parser/)."""
    # flat_parser/src/config/settings.py  →  flat_parser/config/
    current = Path(__file__).resolve()
    # walk up until we find config/ directory at the same level as src/
    for parent in current.parents:
        if (parent / "config" / "settings.yaml").exists():
            return parent / "config"
    # fallback: assume we run from flat_parser/
    return Path("config")


CONFIG_DIR = _find_config_dir()


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file, return empty dict if not found."""
    import yaml

    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


# ── Sub-models ──────────────────────────────────────────────────────────────


class LLMSettings(BaseModel):
    base_url: str = "http://localhost:8000/v1"
    model: str = "qwen36"
    temperature: float = 0.3
    max_tokens: int = 2000
    reasoning_enabled: bool = True
    reasoning_for_recheck: bool = False


class TelegramSettings(BaseModel):
    token: str = ""
    channel_id: str = ""
    test_mode: bool = True


class DatabaseSettings(BaseModel):
    url: str = "sqlite+aiosqlite:///./data/realty.db"


class LoggingSettings(BaseModel):
    level: str = "INFO"
    file: str = "logs/app.log"
    rotation: str = "10 MB"
    retention: str = "30 days"


class ScraperSettings(BaseModel):
    delay_between_requests: float = 2.0
    delay_between_pages: float = 3.0
    max_pages_per_query: int = 5
    timeout: int = 30
    user_agents: list[str] = Field(
        default_factory=lambda: [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        ]
    )


class SchedulerSettings(BaseModel):
    fetch_listings_interval_min: int = 60
    fetch_details_interval_min: int = 15
    evaluate_new_interval_min: int = 20
    check_cold_storage_interval_min: int = 120
    cleanup_interval_hours: int = 24
    market_stats_interval_hours: int = 24


class ColdStorageSettings(BaseModel):
    warm_check_interval_hours: int = 24
    cold_check_interval_hours: int = 72
    max_checks_before_remove: int = 5
    ttl_days: int = 30
    price_drop_threshold_pct: float = 5.0


# ── Main Settings ───────────────────────────────────────────────────────────


class Settings(BaseSettings):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    scraper: ScraperSettings = Field(default_factory=ScraperSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    cold_storage: ColdStorageSettings = Field(default_factory=ColdStorageSettings)

    # Paths
    config_dir: Path = CONFIG_DIR
    data_dir: Path = Path("data")
    log_dir: Path = Path("logs")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def load_settings() -> Settings:
    """Load settings from YAML + .env + env vars.

    Priority: env vars > .env > YAML > defaults.
    """
    import yaml

    yaml_path = CONFIG_DIR / "settings.yaml"
    yaml_data: dict[str, Any] = {}
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    settings = Settings()

    # Override from YAML
    if "llm" in yaml_data:
        settings.llm = LLMSettings(**yaml_data["llm"])
    if "telegram" in yaml_data:
        tg_data = dict(yaml_data["telegram"])
        # Resolve ${VAR} references
        tg_data["token"] = os.environ.get("TELEGRAM_TOKEN", tg_data.get("token", ""))
        tg_data["channel_id"] = os.environ.get("TELEGRAM_CHANNEL", tg_data.get("channel_id", ""))
        settings.telegram = TelegramSettings(**tg_data)
    if "database" in yaml_data:
        settings.database = DatabaseSettings(**yaml_data["database"])
    if "logging" in yaml_data:
        settings.logging = LoggingSettings(**yaml_data["logging"])
    if "scraper" in yaml_data:
        settings.scraper = ScraperSettings(**yaml_data["scraper"])
    if "scheduler" in yaml_data:
        settings.scheduler = SchedulerSettings(**yaml_data["scheduler"])
    if "cold_storage" in yaml_data:
        settings.cold_storage = ColdStorageSettings(**yaml_data["cold_storage"])

    # Ensure directories exist
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    return settings


# Singleton
settings = load_settings()
