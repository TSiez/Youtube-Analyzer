"""Google OAuth helper for Sheets / Slides / Drive / Gmail.

YouTube reads use an API key, so they don't need OAuth.
On first run this opens a browser; the resulting token is cached in token.json.
"""
from __future__ import annotations

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


def get_credentials(scopes: Iterable[str] | None = None) -> Credentials:
    """Return valid OAuth credentials, refreshing or re-authorizing as needed."""
    scopes_list = list(scopes) if scopes else SCOPES

    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes_list)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            "credentials.json not found in the project root. "
            "Download it from Google Cloud > APIs & Services > Credentials > OAuth 2.0 Client IDs > Download JSON."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), scopes_list)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds
