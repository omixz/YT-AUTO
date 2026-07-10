"""Shared Google OAuth credential loading for youtube_uploader.py and analytics.py.

Uses the OAuth "installed app" flow: the first run opens a browser for you to
grant access, then caches a refresh token in YOUTUBE_TOKEN_FILE so later runs
(including scheduled/CI runs) don't need interactive login.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import PipelineConfig

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def get_credentials(config: PipelineConfig) -> Credentials:
    token_path = Path(config.secrets.youtube_token_file)
    client_secret_path = Path(config.secrets.youtube_client_secret_file)

    creds: Optional[Credentials] = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_path.exists():
                raise RuntimeError(
                    f"YouTube OAuth client secret not found at {client_secret_path}. "
                    "Create a Desktop-app OAuth client in Google Cloud Console, "
                    "download its JSON, and point YOUTUBE_CLIENT_SECRET_FILE at it."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds
