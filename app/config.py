"""
ShowPulser Configuration
Reads from .env file via pydantic-settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ──────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Discord ───────────────────────────────────────────────────────
    discord_webhook_url: str = ""

    # ── WhatsApp (Green API – free, QR code) ───────────────────────
    greenapi_instance_id: str = ""   # e.g. 710722689231
    greenapi_api_token:   str = ""   # from console.green-api.com
    greenapi_recipient:   str = ""   # digits only e.g. 919876543210
    greenapi_api_url:     str = "https://api.green-api.com"  # instance-specific URL

    # ── Email (SMTP) ──────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_to: str = ""

    # ── Scheduler ─────────────────────────────────────────────────────
    scan_interval_seconds: int = 180

    # ── App ───────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: str = ""
    database_path: str = "data/showpulser.db"
    snapshots_dir: str = "snapshots"
    logs_dir: str = "logs"

    # Comma-separated list of enabled notifiers
    enabled_notifiers: str = "telegram"

    @field_validator("database_path", mode="before")
    @classmethod
    def ensure_db_dir_exists(cls, v: str) -> str:
        Path(v).parent.mkdir(parents=True, exist_ok=True)
        return v

    @field_validator("snapshots_dir", "logs_dir", mode="before")
    @classmethod
    def ensure_dirs_exist(cls, v: str) -> str:
        Path(v).mkdir(parents=True, exist_ok=True)
        return v

    def notifiers_list(self) -> list[str]:
        return [n.strip().lower() for n in self.enabled_notifiers.split(",") if n.strip()]


# Singleton
settings = Settings()
