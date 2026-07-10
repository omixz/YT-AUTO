"""Typed configuration loading: config/channel.yaml plus .env secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ChannelConfig:
    name: str
    niche: str
    audience: str
    tone: str
    language: str = "en"


@dataclass
class VideoConfig:
    format: str = "shorts"
    target_seconds: int = 45
    resolution_shorts: tuple = (1080, 1920)
    resolution_longform: tuple = (1920, 1080)
    fps: int = 30
    background_music: Optional[str] = None
    music_volume_db: float = -22.0

    @property
    def resolution(self) -> tuple:
        return self.resolution_shorts if self.format == "shorts" else self.resolution_longform


@dataclass
class VoiceConfig:
    provider: str = "edge-tts"
    name: str = "en-US-GuyNeural"
    rate: str = "+0%"
    pitch: str = "+0Hz"


@dataclass
class VisualsConfig:
    provider: str = "pexels"
    orientation: str = "portrait"
    min_clip_seconds: int = 3


@dataclass
class UploadConfig:
    privacy_status: str = "private"
    category_id: str = "27"
    default_tags: list = field(default_factory=list)
    made_for_kids: bool = False


@dataclass
class TopicsConfig:
    queue_file: str = "config/topics.yaml"
    history_file: str = "config/topic_history.json"


@dataclass
class Secrets:
    anthropic_api_key: Optional[str] = None
    pexels_api_key: Optional[str] = None
    youtube_client_secret_file: str = "client_secret.json"
    youtube_token_file: str = "token.json"

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            pexels_api_key=os.getenv("PEXELS_API_KEY"),
            youtube_client_secret_file=os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json"),
            youtube_token_file=os.getenv("YOUTUBE_TOKEN_FILE", "token.json"),
        )


@dataclass
class PipelineConfig:
    channel: ChannelConfig
    video: VideoConfig
    voice: VoiceConfig
    visuals: VisualsConfig
    upload: UploadConfig
    topics: TopicsConfig
    secrets: Secrets

    @classmethod
    def load(cls, path: "str | Path | None" = None) -> "PipelineConfig":
        path = Path(path) if path else ROOT / "config" / "channel.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

        video_raw = dict(raw.get("video", {}))
        for key in ("resolution_shorts", "resolution_longform"):
            if key in video_raw:
                video_raw[key] = tuple(video_raw[key])

        return cls(
            channel=ChannelConfig(**raw["channel"]),
            video=VideoConfig(**video_raw),
            voice=VoiceConfig(**raw.get("voice", {})),
            visuals=VisualsConfig(**raw.get("visuals", {})),
            upload=UploadConfig(**raw.get("upload", {})),
            topics=TopicsConfig(**raw.get("topics", {})),
            secrets=Secrets.from_env(),
        )
