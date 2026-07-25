"""End-to-end orchestration: pick a (niche, format), write a script, run it
past a quality gate, synthesize narration, build visuals (stock footage for
shorts; for longform, a flat-vector-clipart illustration drawn procedurally
per scene - see procedural_illustration.py), append a subscribe-CTA outro,
assemble the video, generate a thumbnail, and (unless dry_run) upload it to
YouTube."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import List, Optional

from . import (
    assembler, branding, buffer_publisher, growth_ledger, media_host, music, niche_selector,
    procedural_illustration, quality_check, scheduling, sound_effects, subtitles, thumbnail, topic_store, tts,
    visuals, youtube_uploader,
)
from .config import ROOT, PipelineConfig
from .script_writer import generate_script
from .tts import SceneAudio
from .visuals import VisualAsset

logger = logging.getLogger(__name__)

KEEP_FILES = {"final.mp4", "thumbnail.jpg", "captions.ass", "manifest.json"}


def _select_niche_and_format(config: PipelineConfig, format_override: Optional[str] = None) -> tuple:
    """Picks (niche_key, format_name) and mutates config in place so every
    other module (script_writer, branding, quality_check, assembler, ...)
    just keeps reading config.channel.niche / config.video.format like
    before - see ChannelConfig.niche / VideoConfig.format docstrings."""
    niche_key, format_name = niche_selector.choose(config, format_override=format_override)
    niche = next(n for n in config.niches if n.key == niche_key)

    config.channel.niche = niche.niche
    config.channel.audience = niche.audience or config.channel.audience
    config.channel.tone = niche.tone or config.channel.tone

    config.video.format = format_name
    config.video.target_seconds = config.video.formats[format_name].target_seconds
    config.visuals.orientation = "portrait" if format_name == "shorts" else "landscape"

    return niche_key, format_name


def _build_content_visuals(script, content_scene_audio: List[SceneAudio], config: PipelineConfig, work_dir: Path) -> List[VisualAsset]:
    if config.video.format == "longform":
        # One animated flat-vector-clipart clip per scene: the scene's setting
        # drawn directly, with the focal subject (the thing being narrated)
        # floating/bobbing over it - see procedural_illustration.py. Each clip
        # is sized to its scene's narration length and handed to assembler.py
        # as a video segment (kind="video").
        durations = [a.duration for a in content_scene_audio]
        paths = procedural_illustration.generate_all_clips(script.scenes, durations, config, work_dir, title=script.title)
        return [VisualAsset(kind="video", path=p) for p in paths]
    return visuals.fetch_all(script.scenes, config, work_dir)


def run(
    config: PipelineConfig,
    topic_override: Optional[str] = None,
    dry_run: bool = False,
    publish_at: Optional[str] = None,
    publish_now: bool = False,
    keep_work_dir: bool = False,
    format_override: Optional[str] = None,
) -> dict:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    work_dir = ROOT / "output" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    niche_key, format_name = _select_niche_and_format(config, format_override=format_override)
    logger.info("Selected niche=%s format=%s", niche_key, format_name)

    logger.info("Picking topic...")
    topic = topic_store.next_topic(config, niche_key, override=topic_override)
    logger.info("Topic: %s", topic)

    logger.info("Writing script...")
    script = generate_script(topic, config)
    logger.info("Title: %s (%d scenes)", script.title, len(script.scenes))

    # Script-level checks run now (cheap, and useful to see in the logs
    # before spending render time); media-level checks (below, after the
    # video is actually built) get combined into the same final verdict -
    # see quality_check.py's module docstring for why the two are split.
    text_passed, text_reasons = quality_check.check(script, config)
    if not text_passed:
        logger.warning("Script quality gate failed: %s", "; ".join(text_reasons))

    logger.info("Synthesizing narration...")
    content_scene_audio, content_narration_path = tts.synthesize_script(
        script, config.voice, work_dir, google_api_key=config.secrets.google_tts_api_key,
    )

    logger.info("Building %s visuals...", "illustrated" if format_name == "longform" else "stock")
    content_visuals = _build_content_visuals(script, content_scene_audio, config, work_dir)

    logger.info("Building outro...")
    # No channel-branded intro card - the video opens directly on content.
    outro_visual, outro_audio = branding.build_outro(config, work_dir)

    all_scene_audio = content_scene_audio + [outro_audio]
    all_visuals = content_visuals + [outro_visual]

    narration_path = tts.concat_audio(
        [content_narration_path, outro_audio.audio_path],
        work_dir / "narration_final.mp3",
    )

    logger.info("Building captions...")
    ass_path = subtitles.build_ass(all_scene_audio, work_dir / "captions.ass", config.video.resolution)

    logger.info("Building ambient sound effects...")
    ambience_path = sound_effects.build_ambience_track(
        script.scenes, content_scene_audio, 0.0, outro_audio.duration, work_dir,
    )

    logger.info("Assembling final video...")
    # Use a configured music file if one is set, otherwise synthesize an
    # ambient bed sized to the whole video (see music.py) - every video gets
    # background music without needing an external, copyrighted track.
    if config.video.background_music:
        music_path = Path(config.video.background_music)
    else:
        total_duration = sum(a.duration for a in all_scene_audio)
        music_path = music.build_music_bed(total_duration, work_dir)
    video_path = assembler.build_video(
        all_visuals, all_scene_audio, narration_path, ass_path, config, work_dir,
        work_dir / "final.mp4", background_music=music_path, ambience_path=ambience_path,
    )

    logger.info("Checking rendered media (video/audio/captions)...")
    media_passed, media_reasons = quality_check.check_media(video_path, all_scene_audio, ass_path, config)
    passed_quality_gate = text_passed and media_passed
    quality_reasons = text_reasons + media_reasons
    if not passed_quality_gate:
        logger.warning("Quality gate failed: %s", "; ".join(quality_reasons))

    logger.info("Generating thumbnail...")
    thumb_path = thumbnail.generate(
        script.title, content_visuals[0], work_dir, work_dir / "thumbnail.jpg"
    )

    manifest = {
        "run_id": run_id,
        "niche": niche_key,
        "format": format_name,
        "topic": topic,
        "title": script.title,
        "description": script.description,
        "tags": script.tags,
        "video_path": str(video_path),
        "thumbnail_path": str(thumb_path),
        "passed_quality_gate": passed_quality_gate,
        "quality_gate_reasons": quality_reasons,
    }

    if dry_run:
        logger.info("Dry run: skipping upload. Review the output at %s", video_path)
    else:
        effective_privacy = (
            config.upload.privacy_status if passed_quality_gate else config.quality.fallback_privacy_status
        )
        if not passed_quality_gate:
            logger.warning(
                "Uploading as '%s' instead of '%s' because the quality gate failed - review by hand.",
                effective_privacy, config.upload.privacy_status,
            )

        # A quality-gate failure means a human needs to review this by hand,
        # not have it auto-publish later unattended - only schedule the
        # optimal slot on the normal (passed-gate) path, and only when the
        # caller hasn't already pinned a specific publish_at themselves.
        effective_publish_at = publish_at
        if effective_publish_at is None and passed_quality_gate and not publish_now:
            effective_publish_at = scheduling.next_optimal_publish_time()
            logger.info("Scheduling publish for the next optimal slot: %s", effective_publish_at)
        elif publish_now:
            logger.info("publish_now set - releasing immediately instead of scheduling an optimal slot.")

        logger.info("Uploading to YouTube...")
        try:
            # Only the upload call itself should trigger the Buffer fallback
            # below - once upload_video() returns, the video is already live
            # on YouTube, so a failure in bookkeeping (e.g. record_published's
            # ledger file write) must not be mistaken for an upload failure
            # and must not cause a second, duplicate publish via Buffer.
            video_id = youtube_uploader.upload_video(
                video_path, script.title, script.description, script.tags, config,
                thumbnail_path=thumb_path, publish_at=effective_publish_at,
                privacy_status_override=effective_privacy,
            )
        except Exception as exc:
            # The direct YouTube OAuth path is primary; Buffer (posting
            # through its own connected-channel auth, entirely separate from
            # this project's token) is only a fallback for exactly this
            # failure mode - e.g. the OAuth token expired/was revoked - not
            # a general retry-anything handler. It does carry the same
            # effective privacy/category/made-for-kids settings as the
            # primary path (see buffer_publisher.py for how those map onto
            # Buffer's YouTube-specific metadata fields), it just can't set
            # a custom thumbnail or tags the way the direct API upload can.
            #
            # Confirmed against a live account: Buffer's YouTube integration
            # only supports Shorts (vertical, <=3 min) - a longform video is
            # rejected outright regardless of any field set here (see
            # buffer_publisher.py's module docstring). Attempting it for a
            # longform run would just add a doomed network round-trip before
            # still failing, so only try it for "shorts".
            if format_name != "shorts":
                logger.error(
                    "Direct YouTube upload failed (%s) - not attempting the Buffer fallback, since Buffer's "
                    "YouTube integration only supports Shorts and this run is '%s'.", exc, format_name,
                )
                raise

            logger.warning("Direct YouTube upload failed (%s) - trying the Buffer fallback...", exc)
            video_url = media_host.upload_public(video_path, f"{run_id}.mp4", config)
            buffer_post_id = buffer_publisher.publish_video(
                video_url, script.title, script.description, config, publish_at=effective_publish_at,
                privacy_status=effective_privacy, category_id=config.upload.category_id,
                made_for_kids=config.upload.made_for_kids,
            )
            manifest["buffer_post_id"] = buffer_post_id
            manifest["published_via"] = "buffer_fallback"
            manifest["privacy_status"] = effective_privacy
            manifest["publish_at"] = effective_publish_at
            logger.warning(
                "Published via the Buffer fallback (post %s) - no YouTube video ID is known yet "
                "(Buffer publishes asynchronously), so this run is NOT recorded in the growth ledger.",
                buffer_post_id,
            )
        else:
            manifest["youtube_video_id"] = video_id
            manifest["youtube_url"] = f"https://youtu.be/{video_id}"
            manifest["privacy_status"] = effective_privacy
            manifest["publish_at"] = effective_publish_at
            manifest["published_via"] = "youtube_api"

            growth_ledger.record_published(
                niche_key, format_name, video_id, title=script.title, topic=topic,
            )

    (work_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not keep_work_dir:
        for item in work_dir.iterdir():
            if item.name in KEEP_FILES:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    return manifest
