"""Google OAuth helper for Sheets / Slides / Drive / Gmail.

YouTube reads use an API key, so they don't need OAuth.

Local: first run opens a browser; the resulting token is cached in token.json.
Headless (Render etc.): set OAUTH_NONINTERACTIVE=1 and provide a previously
generated token.json (with a refresh token) — it is refreshed automatically
without a browser. A raw service account is intentionally NOT used because it
cannot send Gmail as a personal @gmail.com account.
"""
from __future__ import annotations

import os
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import CREDENTIALS_PATH, TOKEN_PATH

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.send",
]


def _save_token(creds: Credentials) -> None:
    """Persist the (possibly refreshed) token. Best-effort: a read-only secret
    mount on a server will raise, which is fine — the creds are valid in-memory
    for this run regardless."""
    try:
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    except OSError:
        pass


def get_credentials(scopes: Iterable[str] | None = None) -> Credentials:
    """Return valid OAuth credentials, refreshing or re-authorizing as needed."""
    scopes_list = list(scopes) if scopes else SCOPES

    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes_list)

    if creds and creds.valid:
        return creds

    # Refresh headlessly — works on a server with no browser.
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
        return creds

    # From here we'd need interactive consent (a browser). Refuse on servers.
    if os.getenv("OAUTH_NONINTERACTIVE") == "1":
        raise RuntimeError(
            "Google auth needs a valid token.json, but none is usable and "
            "OAUTH_NONINTERACTIVE=1 (no browser available on this host).\n"
            "Fix: generate token.json locally (run a Weekly Trends report once and "
            "approve the browser prompt), then add credentials.json AND token.json as "
            "Render secret files. Set the OAuth consent screen to 'In production' so the "
            "refresh token does not expire every 7 days."
        )

    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            "credentials.json not found. Download the OAuth 2.0 Desktop client JSON "
            "from Google Cloud > APIs & Services > Credentials, and place it in the project root."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), scopes_list)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds
