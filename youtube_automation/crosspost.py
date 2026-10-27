"""Best-effort cross-posting of finished PUBLIC Shorts. Never raises: a TikTok problem must not fail the run."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import buffer_publisher, media_host
from .config import PipelineConfig

logger = logging.getLogger(__name__)


def tiktok(config: PipelineConfig, *, format_name: str, privacy: str, passed_gate: bool, dry_run: bool,
           video_path: Path, run_id: str, title: str) -> Optional[str]:
    """Returns the Buffer post id, or None if skipped/failed."""
    s = config.secrets
    if dry_run or format_name != "shorts" or privacy != "public" or not passed_gate:
        return None
    if not (config.upload.crosspost_tiktok and s.buffer_api_key and s.buffer_tiktok_channel_id):
        logger.info("TikTok cross-post skipped (disabled or BUFFER_API_KEY / BUFFER_TIKTOK_CHANNEL_ID not set).")
        return None
    try:
        url = media_host.upload_public(video_path, f"{run_id}.mp4", config)
        caption = f"{title}\n\nFull-length videos on YouTube.\n{config.upload.tiktok_hashtags}"
        return buffer_publisher.publish_tiktok(url, caption, config)
    except Exception:  # noqa: BLE001
        logger.exception("TikTok cross-post failed (the YouTube upload is unaffected).")
        return None
