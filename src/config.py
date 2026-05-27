"""Centralized config loaded from .env and CLI overrides."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "token.json"

load_dotenv(ENV_PATH)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]


@dataclass
class Config:
    youtube_api_key: str = ""
    spreadsheet_id: str = ""
    presentation_id: str = ""
    recipient_email: str = ""
    sender_email: str = ""
    channels: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    lookback_days: int = 7
    max_results: int = 10

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
            spreadsheet_id=os.getenv("SPREADSHEET_ID", "").strip(),
            presentation_id=os.getenv("PRESENTATION_ID", "").strip(),
            recipient_email=os.getenv("RECIPIENT_EMAIL", "").strip(),
            sender_email=os.getenv("SENDER_EMAIL", "").strip(),
            channels=_split_csv(os.getenv("YT_CHANNELS")),
            keywords=_split_csv(os.getenv("YT_KEYWORDS")),
            lookback_days=int(os.getenv("LOOKBACK_DAYS", "7") or 7),
            max_results=int(os.getenv("MAX_RESULTS", "10") or 10),
        )

    def require_youtube_key(self) -> None:
        if not self.youtube_api_key:
            raise RuntimeError(
                "YOUTUBE_API_KEY is missing. Add it to .env (Google Cloud > Credentials > API Keys)."
            )

    def require_email(self) -> None:
        if not self.recipient_email or not self.sender_email:
            raise RuntimeError(
                "RECIPIENT_EMAIL and SENDER_EMAIL must be set in .env before sending mail."
            )


def write_env_value(key: str, value: str) -> None:
    """Update or append a key=value pair in .env, preserving other lines."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    found = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
