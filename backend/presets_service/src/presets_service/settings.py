"""
Configuration for Presets Service.

Uses pydantic-settings for environment-based configuration.
All settings can be overridden via PRESETS_ prefixed env vars.
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from PRESETS_ environment variables."""

    service_name: str = "presets_service"

    host: str = "0.0.0.0"
    port: int = 8005

    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]

    # SQLite database path (PostgreSQL migration later)
    db_path: Path = Path("/tmp/presets.db")

    # Optional path to a directory containing seed JSON files.
    # On first run (empty DB), any *_seed.json files here are loaded.
    seed_path: Optional[Path] = None

    model_config = SettingsConfigDict(
        env_prefix="PRESETS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
