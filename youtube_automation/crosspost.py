"""Best-effort cross-posting of finished PUBLIC Shorts. Never raises: a TikTok problem must not fail the run."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import buffer_publisher, media_host
from .config import PipelineConfig

logger = logging.getLogger(__name__)


def _channel_name(video_id: Optional[str]) -> Optional[str]:
    """The YouTube channel's display name via oEmbed (free, no key)."""
    if not video_id:
        return None
    try:
        import json
        import urllib.request
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.load(r).get("author_name")
    except Exception:  # noqa: BLE001
        return None


def build_caption(title: str, search_phrase: Optional[str], channel_name: Optional[str], hashtags: str) -> str:
    """TikTok exists to feed YouTube: every caption says where the full story is and exactly what to search."""
    where = f"the full story on YouTube{f' ({channel_name})' if channel_name else ''}"
    lines = [title, "", "\U0001F44D Like & follow for a new story every day"]
    lines.append(f"\u25B6\uFE0F Watch {where}: search \"{search_phrase}\"" if search_phrase else f"\u25B6\uFE0F Watch {where} - link in bio")
    lines += ["\U0001F514 Subscribe on YouTube so you never miss one", hashtags]
    return "\n".join(lines)


def tiktok(config: PipelineConfig, *, format_name: str, privacy: str, passed_gate: bool, dry_run: bool,
           video_path: Path, run_id: str, title: str, video_id: Optional[str] = None, search_phrase: Optional[str] = None) -> Optional[str]:
    """Returns the Buffer post id, or None if skipped/failed."""
    s = config.secrets
    if dry_run or format_name != "shorts" or privacy != "public" or not passed_gate:
        return None
    if not (config.upload.crosspost_tiktok and s.buffer_api_key and s.buffer_tiktok_channel_id):
        logger.info("TikTok cross-post skipped (disabled or BUFFER_API_KEY / BUFFER_TIKTOK_CHANNEL_ID not set).")
        return None
    try:
        url = media_host.upload_public(video_path, f"{run_id}.mp4", config)
        caption = build_caption(title, search_phrase, _channel_name(video_id), config.upload.tiktok_hashtags)
        return buffer_publisher.publish_tiktok(url, caption, config, title=title)
    except Exception:  # noqa: BLE001
        logger.exception("TikTok cross-post failed (the YouTube upload is unaffected).")
        return None
