"""End-to-end orchestration: pick a topic, write a script, run it past a
quality gate, synthesize narration, fetch visuals, wrap it in a branded
intro/outro, assemble the video, generate a thumbnail, and (unless dry_run)
upload it to YouTube."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from . import assembler, branding, quality_check, subtitles, thumbnail, topic_store, tts, visuals, youtube_uploader
from .config import ROOT, PipelineConfig
from .script_writer import generate_script

logger = logging.getLogger(__name__)

KEEP_FILES = {"final.mp4", "thumbnail.jpg", "captions.srt", "manifest.json"}


def run(
    config: PipelineConfig,
    topic_override: Optional[str] = None,
    dry_run: bool = False,
    publish_at: Optional[str] = None,
    keep_work_dir: bool = False,
) -> dict:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    work_dir = ROOT / "output" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Picking topic...")
    topic = topic_store.next_topic(config, override=topic_override)
    logger.info("Topic: %s", topic)

    logger.info("Writing script...")
    script = generate_script(topic, config)
    logger.info("Title: %s (%d scenes)", script.title, len(script.scenes))

    passed_quality_gate, quality_reasons = quality_check.check(script, config)
    if not passed_quality_gate:
        logger.warning("Quality gate failed: %s", "; ".join(quality_reasons))

    logger.info("Synthesizing narration...")
    content_scene_audio, content_narration_path = tts.synthesize_script(script, config.voice, work_dir)

    logger.info("Fetching stock visuals...")
    content_visuals = visuals.fetch_all(script.scenes, config, work_dir)

    logger.info("Building branded intro/outro...")
    intro_visual, intro_audio = branding.build_intro(config, work_dir)
    outro_visual, outro_audio = branding.build_outro(config, work_dir)

    all_scene_audio = [intro_audio] + content_scene_audio + [outro_audio]
    all_visuals = [intro_visual] + content_visuals + [outro_visual]

    narration_path = tts.concat_audio(
        [intro_audio.audio_path, content_narration_path, outro_audio.audio_path],
        work_dir / "narration_final.mp3",
    )

    logger.info("Building captions...")
    srt_path = subtitles.build_srt(all_scene_audio, work_dir / "captions.srt")

    logger.info("Assembling final video...")
    music_path = Path(config.video.background_music) if config.video.background_music else None
    video_path = assembler.build_video(
        all_visuals, all_scene_audio, narration_path, srt_path, config, work_dir,
        work_dir / "final.mp4", background_music=music_path,
    )

    logger.info("Generating thumbnail...")
    thumb_path = thumbnail.generate(
        script.title, content_visuals[0], work_dir, work_dir / "thumbnail.jpg"
    )

    manifest = {
        "run_id": run_id,
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

        logger.info("Uploading to YouTube...")
        video_id = youtube_uploader.upload_video(
            video_path, script.title, script.description, script.tags, config,
            thumbnail_path=thumb_path, publish_at=publish_at,
            privacy_status_override=effective_privacy,
        )
        manifest["youtube_video_id"] = video_id
        manifest["youtube_url"] = f"https://youtu.be/{video_id}"
        manifest["privacy_status"] = effective_privacy

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
