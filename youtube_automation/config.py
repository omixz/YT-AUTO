"""Typed configuration loading: config/channel.yaml plus .env secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ChannelConfig:
    name: str
    audience: str
    tone: str
    language: str = "en"
    subscribe_cta: str = "for more {niche} every week"
    # Mutated per run to whichever niche niche_selector.choose() picked -
    # not meant to be set directly in channel.yaml. Kept here (rather than
    # threaded as a parameter) so script_writer/branding/quality_check can
    # keep reading config.channel.niche unchanged.
    niche: str = ""


@dataclass
class NicheConfig:
    key: str
    niche: str
    audience: Optional[str] = None
    tone: Optional[str] = None
    weight: float = 1.0


@dataclass
class FormatConfig:
    enabled: bool = True
    target_seconds: int = 60
    weight: float = 1.0


@dataclass
class VideoConfig:
    fps: int = 30
    background_music: Optional[str] = None
    music_volume_db: float = -22.0
    sfx_volume_db: float = -23.0
    resolution_shorts: tuple = (1080, 1920)
    resolution_longform: tuple = (1920, 1080)
    formats: Dict[str, FormatConfig] = field(default_factory=dict)
    # Mutated per run by niche_selector's choice - see ChannelConfig.niche.
    format: str = "shorts"
    target_seconds: int = 60
    min_scene_duration: int = 5
    max_scene_duration: int = 15
    target_scene_duration: int = 8

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
class AnimationConfig:
    """Settings for the procedural stick-figure overlay composited onto real
    stock footage/photos for longform."""
    fps: int = 24
    accent_color: tuple = (255, 255, 255)


@dataclass
class UploadConfig:
    privacy_status: str = "private"
    category_id: str = "27"
    default_tags: list = field(default_factory=list)
    made_for_kids: bool = False


@dataclass
class QualityConfig:
    min_words: int = 90
    min_scenes: int = 6
    require_hook_and_insight: bool = True
    require_strong_hook: bool = True
    fallback_privacy_status: str = "private"


@dataclass
class TopicsConfig:
    queue_file: str = "config/topics/{niche}.yaml"
    history_file: str = "config/topic_history/{niche}.json"


@dataclass
class GrowthConfig:
    """Drives the (niche, format) selection bandit - see niche_selector.py."""
    stats_file: str = "config/performance_stats.json"
    maturity_days: int = 7
    epsilon: float = 0.2
    min_samples_for_trust: int = 3


@dataclass
class Secrets:
    gemini_api_key: Optional[str] = None
    pexels_api_key: Optional[str] = None
    youtube_client_secret_file: str = "client_secret.json"
    youtube_token_file: str = "token.json"

    # google_tts.py (voice.provider == "google" in channel.yaml) - Neural2
    # voices, 1M characters/month free. tts.py falls back to edge-tts
    # automatically if this is unset, so leaving it blank never breaks a run.
    google_tts_api_key: Optional[str] = None

    # buffer_publisher.py's fallback path (only used when the direct YouTube
    # OAuth upload fails, e.g. an expired/revoked token) - posts through
    # Buffer's connected YouTube channel instead. See media_host.py for the
    # S3-compatible bucket Buffer's API requires (it needs a public URL, not
    # a file upload) and buffer_publisher.py's module docstring for why this
    # is a deliberately best-effort fallback, not a primary upload path.
    buffer_api_key: Optional[str] = None
    buffer_youtube_channel_id: Optional[str] = None
    media_host_bucket: Optional[str] = None
    media_host_access_key: Optional[str] = None
    media_host_secret_key: Optional[str] = None
    media_host_endpoint_url: Optional[str] = None  # blank/None for real AWS S3
    media_host_region: str = "auto"
    media_host_public_base_url: Optional[str] = None  # e.g. https://media.example.com

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            pexels_api_key=os.getenv("PEXELS_API_KEY"),
            youtube_client_secret_file=os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json"),
            youtube_token_file=os.getenv("YOUTUBE_TOKEN_FILE", "token.json"),
            google_tts_api_key=os.getenv("GOOGLE_TTS_API_KEY"),
            buffer_api_key=os.getenv("BUFFER_API_KEY"),
            buffer_youtube_channel_id=os.getenv("BUFFER_YOUTUBE_CHANNEL_ID"),
            media_host_bucket=os.getenv("MEDIA_HOST_BUCKET"),
            media_host_access_key=os.getenv("MEDIA_HOST_ACCESS_KEY"),
            media_host_secret_key=os.getenv("MEDIA_HOST_SECRET_KEY"),
            media_host_endpoint_url=os.getenv("MEDIA_HOST_ENDPOINT_URL"),
            media_host_region=os.getenv("MEDIA_HOST_REGION", "auto"),
            media_host_public_base_url=os.getenv("MEDIA_HOST_PUBLIC_BASE_URL"),
        )


@dataclass
class PipelineConfig:
    channel: ChannelConfig
    niches: List[NicheConfig]
    video: VideoConfig
    voice: VoiceConfig
    visuals: VisualsConfig
    animation: AnimationConfig
    upload: UploadConfig
    quality: QualityConfig
    topics: TopicsConfig
    growth: GrowthConfig
    secrets: Secrets

    @classmethod
    def load(cls, path: "str | Path | None" = None) -> "PipelineConfig":
        path = Path(path) if path else ROOT / "config" / "channel.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

        video_raw = dict(raw.get("video", {}))
        formats_raw = video_raw.pop("formats", {})
        for key in ("resolution_shorts", "resolution_longform"):
            if key in video_raw:
                video_raw[key] = tuple(video_raw[key])
        formats = {name: FormatConfig(**cfg) for name, cfg in formats_raw.items()}

        niches = [NicheConfig(**n) for n in raw.get("niches", [])]
        if not niches:
            raise ValueError("config/channel.yaml must define at least one entry under 'niches:'.")

        animation_raw = dict(raw.get("animation", {}))
        if "accent_color" in animation_raw:
            animation_raw["accent_color"] = tuple(animation_raw["accent_color"])

        return cls(
            channel=ChannelConfig(**raw["channel"]),
            niches=niches,
            video=VideoConfig(**video_raw, formats=formats),
            voice=VoiceConfig(**raw.get("voice", {})),
            visuals=VisualsConfig(**raw.get("visuals", {})),
            animation=AnimationConfig(**animation_raw),
            upload=UploadConfig(**raw.get("upload", {})),
            quality=QualityConfig(**raw.get("quality", {})),
            topics=TopicsConfig(**raw.get("topics", {})),
            growth=GrowthConfig(**raw.get("growth", {})),
            secrets=Secrets.from_env(),
        )
