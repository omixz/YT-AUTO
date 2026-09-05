"""Uploads a finished video to YouTube via the Data API v3."""
from __future__ import annotations

import http.client
import logging
import random
import time
from pathlib import Path
from typing import List, Optional

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import PipelineConfig
from .youtube_auth import get_credentials

logger = logging.getLogger(__name__)

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

# request.next_chunk() during a resumable upload has no built-in retry - a
# single transient blip (network hiccup, YouTube 5xx) kills the whole upload
# with zero retry, even though everything upstream (rendering, TTS, script
# generation) succeeded. This matters more now that videos are ~3x bigger
# (20 min vs the old 7 min target): a longer upload gives a transient error
# more time to occur, and for longform there's no Buffer fallback to catch a
# failed upload - it's a hard failure for the whole day's video. This is
# Google's own documented retry pattern for resumable uploads (see the
# google-api-python-client resumable upload sample), matching the same
# retry/backoff style used in script_writer.py for Gemini calls.
_RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
_RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    http.client.NotConnected,
    http.client.IncompleteRead,
    http.client.ImproperConnectionState,
    http.client.CannotSendRequest,
    http.client.CannotSendHeader,
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
    ConnectionError,
    TimeoutError,
)
_MAX_UPLOAD_RETRIES = 8
_MAX_BACKOFF_SECONDS = 60


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
    retry_count = 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress:
                logger.info("Upload progress: %d%%", int(progress.progress() * 100))
        except HttpError as exc:
            if exc.resp.status not in _RETRIABLE_STATUS_CODES or retry_count >= _MAX_UPLOAD_RETRIES:
                raise
            retry_count += 1
            sleep_for = min(2 ** retry_count + random.uniform(0, 1), _MAX_BACKOFF_SECONDS)
            logger.warning(
                "Upload chunk failed with HTTP %s (attempt %d/%d), retrying in %.0fs: %s",
                exc.resp.status, retry_count, _MAX_UPLOAD_RETRIES, sleep_for, exc,
            )
            time.sleep(sleep_for)
        except _RETRIABLE_EXCEPTIONS as exc:
            if retry_count >= _MAX_UPLOAD_RETRIES:
                raise
            retry_count += 1
            sleep_for = min(2 ** retry_count + random.uniform(0, 1), _MAX_BACKOFF_SECONDS)
            logger.warning(
                "Upload chunk failed with %s (attempt %d/%d), retrying in %.0fs: %s",
                type(exc).__name__, retry_count, _MAX_UPLOAD_RETRIES, sleep_for, exc,
            )
            time.sleep(sleep_for)

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


def set_video_privacy(video_id: str, privacy_status: str, config: PipelineConfig) -> str:
    """Sets a video's privacyStatus directly (e.g. "public" to release a
    scheduled video immediately, or "private" to unschedule/pull one back).

    videos.update with part='status' replaces the whole status object, so
    omitting publishAt here always clears any pending scheduled release.
    Returns the resulting privacyStatus.
    """
    creds = get_credentials(config)
    youtube = build(API_SERVICE_NAME, API_VERSION, credentials=creds)
    response = youtube.videos().update(
        part="status",
        body={
            "id": video_id,
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": config.upload.made_for_kids,
            },
        },
    ).execute()
    status = response["status"]["privacyStatus"]
    logger.info("Video %s is now %s: https://youtu.be/%s", video_id, status, video_id)
    return status
