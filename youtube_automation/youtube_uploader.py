"""Uploads a finished video to YouTube via the Data API v3.

Uses the OAuth "installed app" flow: the first run opens a browser for you to
grant access, then caches a refresh token in YOUTUBE_TOKEN_FILE so later runs
(including scheduled/CI runs) don't need interactive login.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import PipelineConfig

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


def _get_credentials(config: PipelineConfig) -> Credentials:
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


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: List[str],
    config: PipelineConfig,
    thumbnail_path: Optional[Path] = None,
    publish_at: Optional[str] = None,
) -> str:
    """Uploads video_path to YouTube. Returns the new video's ID."""
    creds = _get_credentials(config)
    youtube = build(API_SERVICE_NAME, API_VERSION, credentials=creds)

    status = {
        "privacyStatus": config.upload.privacy_status,
        "selfDeclaredMadeForKids": config.upload.made_for_kids,
    }
    if publish_at:
        # A scheduled release must stay private until publishAt, per the API.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": list(dict.fromkeys((tags or []) + config.upload.default_tags)),
            "categoryId": config.upload.category_id,
        },
        "status": status,
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            logger.info("Upload progress: %d%%", int(progress.progress() * 100))

    video_id = response["id"]
    logger.info("Uploaded video %s: https://youtu.be/%s", video_id, video_id)

    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))
            ).execute()
        except HttpError as exc:
            logger.warning(
                "Thumbnail upload failed (channel may need phone verification "
                "for custom thumbnails): %s", exc,
            )

    return video_id
