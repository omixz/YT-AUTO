"""Uploads a finished video to YouTube via the Data API v3."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import PipelineConfig
from .youtube_auth import get_credentials

logger = logging.getLogger(__name__)

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: List[str],
    config: PipelineConfig,
    thumbnail_path: Optional[Path] = None,
    publish_at: Optional[str] = None,
    privacy_status_override: Optional[str] = None,
) -> str:
    """Uploads video_path to YouTube. Returns the new video's ID.

    privacy_status_override lets callers (e.g. a failed quality gate) publish
    more cautiously than config.upload.privacy_status for one specific run.
    """
    creds = get_credentials(config)
    youtube = build(API_SERVICE_NAME, API_VERSION, credentials=creds)

    status = {
        "privacyStatus": privacy_status_override or config.upload.privacy_status,
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
