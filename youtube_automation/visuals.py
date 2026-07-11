"""Finds and downloads stock footage/photos from Pexels for each scene.

Tries each scene's visual_keywords in order, preferring video over stills,
and falls back to a generic niche-appropriate search if nothing matches.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests

from .config import PipelineConfig
from .script_writer import Scene

logger = logging.getLogger(__name__)

VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
PHOTO_SEARCH_URL = "https://api.pexels.com/v1/search"
FALLBACK_KEYWORDS = ["abstract background", "nature timelapse"]


@dataclass
class VisualAsset:
    kind: str  # "video" | "image" | "prerendered" (animation.py's already-animated longform clips)
    path: Path
    source_duration: Optional[float] = None  # only known for video


def _headers(config: PipelineConfig) -> dict:
    if not config.secrets.pexels_api_key:
        raise RuntimeError(
            "PEXELS_API_KEY is not set. Add it to youtube-automation/.env "
            "(copy .env.example first)."
        )
    return {"Authorization": config.secrets.pexels_api_key}


def _best_video_file(video_files: list, target_width: int) -> Optional[dict]:
    mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4" and f.get("width")]
    if not mp4_files:
        return None
    return min(mp4_files, key=lambda f: abs(f["width"] - target_width))


def _search_video(keyword: str, orientation: str, target_width: int, config: PipelineConfig) -> Optional[dict]:
    resp = requests.get(
        VIDEO_SEARCH_URL,
        headers=_headers(config),
        params={"query": keyword, "orientation": orientation, "per_page": 5},
        timeout=20,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        return None
    best_file = None
    best_duration = None
    for video in videos:
        candidate = _best_video_file(video.get("video_files", []), target_width)
        if candidate:
            best_file = candidate
            best_duration = video.get("duration")
            break
    if not best_file:
        return None
    return {"url": best_file["link"], "duration": best_duration}


def _search_photo(keyword: str, orientation: str, config: PipelineConfig) -> Optional[str]:
    resp = requests.get(
        PHOTO_SEARCH_URL,
        headers=_headers(config),
        params={"query": keyword, "orientation": orientation, "per_page": 5},
        timeout=20,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        return None
    return photos[0]["src"]["large2x"]


def _download(url: str, dest: Path) -> Path:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def fetch_visual_for_scene(scene: Scene, index: int, config: PipelineConfig, work_dir: Path) -> VisualAsset:
    target_width = config.video.resolution[0]
    keywords = list(scene.visual_keywords) + FALLBACK_KEYWORDS

    for keyword in keywords:
        try:
            video = _search_video(keyword, config.visuals.orientation, target_width, config)
        except requests.RequestException as exc:
            logger.warning("Pexels video search failed for %r: %s", keyword, exc)
            video = None

        if video:
            path = work_dir / f"scene_{index:02d}_visual.mp4"
            _download(video["url"], path)
            return VisualAsset(kind="video", path=path, source_duration=video["duration"])

    for keyword in keywords:
        try:
            photo_url = _search_photo(keyword, config.visuals.orientation, config)
        except requests.RequestException as exc:
            logger.warning("Pexels photo search failed for %r: %s", keyword, exc)
            photo_url = None

        if photo_url:
            path = work_dir / f"scene_{index:02d}_visual.jpg"
            _download(photo_url, path)
            return VisualAsset(kind="image", path=path)

    raise RuntimeError(
        f"Could not find any stock video or photo for scene {index} "
        f"(tried keywords: {keywords}). Check PEXELS_API_KEY and network access."
    )


def fetch_all(scenes: List[Scene], config: PipelineConfig, work_dir: Path) -> List[VisualAsset]:
    return [fetch_visual_for_scene(scene, i, config, work_dir) for i, scene in enumerate(scenes)]
