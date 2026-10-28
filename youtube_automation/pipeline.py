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
    assembler, branding, buffer_publisher, crosspost, youtube_suggest, growth_ledger, media_host, music, niche_selector,
    cinematic, procedural_illustration, quality_check, scheduling, sound_effects, subtitles, thumbnail, topic_store, tts,
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
    durations = [a.duration for a in content_scene_audio]
    paths = None
    _engine_used[0] = "legacy"
    if config.animation.engine == "toon":
        try:
            from .toon import render as toon_render
            # The toon engine does its own finishing (vignette, time-of-day tint), so no cinematic pass.
            # It renders any frame size, so longform (16:9) and Shorts (9:16) share one engine.
            paths = toon_render.generate_all_clips(script.scenes, durations, config, work_dir,
                                                   title=script.title, scene_audio=content_scene_audio)
            _engine_used[0] = "toon"
        except Exception:
            logger.exception("Toon engine failed outright; falling back for this video.")
    if paths is not None:
        return [VisualAsset(kind="video", path=p) for p in paths]
    if config.video.format == "longform":
        # Legacy: one animated flat-vector-clipart clip per scene (procedural_illustration.py), each sized to
        # its scene's narration length and handed to assembler.py as a video segment.
        paths = procedural_illustration.generate_all_clips(script.scenes, durations, config, work_dir, title=script.title)
        if config.animation.cinematic:
            w, h = config.video.resolution
            paths = cinematic.grade_all(paths, script.scenes, w, h, config.video.fps, work_dir,
                                        budget_seconds=config.animation.cinematic_budget_seconds)
        return [VisualAsset(kind="video", path=p) for p in paths]
    return visuals.fetch_all(script.scenes, config, work_dir)   # Shorts fallback: real stock footage


_engine_used = ["legacy"]   # which renderer actually produced the visuals (set in _build_content_visuals)


class QualityGateFailed(RuntimeError):
    """Raised when a video fails the gate and quality.on_gate_failure == 'skip'."""


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

    max_attempts = max(1, int(config.quality.max_script_attempts))
    for attempt in range(1, max_attempts + 1):
        logger.info("Writing script (attempt %d/%d)...", attempt, max_attempts)
        script = generate_script(topic, config)
        logger.info("Title: %s (%d scenes)", script.title, len(script.scenes))
        # Script-level checks run now (cheap, before spending render time); media-level checks
        # (below, after the video is built) join the same final verdict - see quality_check.py.
        script.title = quality_check.soften_title(script.title)
        dropped = quality_check.drop_defective_scenes(script)
        if dropped:
            logger.warning("Dropped %d defective scene(s) (refused/duplicate/fragment) instead of failing the video.", dropped)
        text_passed, text_reasons = quality_check.check(script, config)
        if text_passed:
            break
        logger.warning("Script quality gate failed (attempt %d/%d): %s", attempt, max_attempts, "; ".join(text_reasons))

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
    on_screen_texts = [s.on_screen_text for s in script.scenes] + [""]
    ass_path = subtitles.build_ass(
        all_scene_audio, work_dir / "captions.ass", config.video.resolution,
        on_screen_texts=on_screen_texts,
    )

    logger.info("Building ambient sound effects...")
    ambience_path = sound_effects.build_ambience_track(
        script.scenes, content_scene_audio, 0.0, outro_audio.duration, work_dir,
    )

    logger.info("Building transition sound effects...")
    scene_durations = [a.duration for a in content_scene_audio]
    scene_roles_for_audio = [s.role for s in script.scenes]
    transitions_path = sound_effects.build_transition_sfx(
        scene_roles_for_audio, scene_durations, work_dir,
    )

    logger.info("Assembling final video...")
    if config.video.background_music:
        music_path = Path(config.video.background_music)
    else:
        total_duration = sum(a.duration for a in all_scene_audio)
        music_path = music.build_music_bed(total_duration, work_dir, scene_durations=scene_durations)
    scene_roles = [s.role for s in script.scenes] + ["build"]
    video_path = assembler.build_video(
        all_visuals, all_scene_audio, narration_path, ass_path, config, work_dir,
        work_dir / "final.mp4", background_music=music_path, ambience_path=ambience_path,
        transitions_path=transitions_path, scene_roles=scene_roles,
    )

    logger.info("Checking rendered media (video/audio/captions)...")
    media_passed, media_reasons = quality_check.check_media(video_path, all_scene_audio, ass_path, config)
    passed_quality_gate = text_passed and media_passed
    quality_reasons = text_reasons + media_reasons
    if not passed_quality_gate:
        logger.warning("Quality gate failed: %s", "; ".join(quality_reasons))
        if config.quality.on_gate_failure == "skip" and not dry_run:
            # Raising (not returning) keeps the workflow's "commit topic state" step from running,
            # so the topic is retried on the next scheduled run. No human needed.
            raise QualityGateFailed("Quality gate failed after %d script attempt(s); skipping upload: %s" % (max_attempts, "; ".join(quality_reasons)))

    logger.info("Generating thumbnail...")
    thumb_path, thumb_style = None, "legacy"
    if config.animation.engine == "toon":
        try:
            from .toon import thumbnail as toon_thumbnail
            thumb_path = toon_thumbnail.render(script.scenes, [a.duration for a in content_scene_audio], script.title,
                                               work_dir / "thumbnail.jpg", script.thumbnail_text)
            thumb_style = "toon"
        except Exception:
            logger.exception("Toon thumbnail failed; falling back to the frame-based thumbnail.")
    if thumb_path is None:
        if content_visuals:
            thumb_path = thumbnail.generate(
                script.title, content_visuals[0], work_dir, work_dir / "thumbnail.jpg",
                candidates=content_visuals[1:8],
            )
        else:
            thumb_path = work_dir / "thumbnail.jpg"

    manifest = {
        "voice": dict(tts.LAST_STATS),
        "thumbnail": {"style": thumb_style, "text": script.thumbnail_text},
        "animation": {"engine": _engine_used[0], **__import__("youtube_automation.toon.render", fromlist=["LAST_STATS"]).LAST_STATS},
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

        # What people really type into YouTube search for this topic: put it in the tags and description so the
        # video can surface for it, and reuse it as the "search for ..." call-to-action on TikTok.
        search_phrase = youtube_suggest.top_query(script.title) or youtube_suggest.top_query(topic)
        description, tags = script.description, list(script.tags)
        if search_phrase:
            if search_phrase.lower() not in [t.lower() for t in tags]:
                tags = [search_phrase] + tags
            if search_phrase.lower() not in description.lower():
                description = f"{description}\n\nSearch YouTube for: {search_phrase}"
        logger.info("Uploading to YouTube (search phrase: %s)...", search_phrase)
        try:
            # Only the upload call itself should trigger the Buffer fallback
            # below - once upload_video() returns, the video is already live
            # on YouTube, so a failure in bookkeeping (e.g. record_published's
            # ledger file write) must not be mistaken for an upload failure
            # and must not cause a second, duplicate publish via Buffer.
            video_id = youtube_uploader.upload_video(
                video_path, script.title, description, tags, config,
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
            tiktok_id = crosspost.tiktok(config, format_name=format_name, privacy=effective_privacy, passed_gate=passed_quality_gate,
                                         dry_run=dry_run, video_path=video_path, run_id=run_id, title=script.title,
                                         video_id=video_id, search_phrase=search_phrase)
            if tiktok_id:
                manifest["tiktok_post_id"] = tiktok_id

            growth_ledger.record_published(
                niche_key, format_name, video_id, title=script.title, topic=topic,
                privacy_status=effective_privacy, passed_quality_gate=passed_quality_gate,
                quality_gate_reasons=quality_reasons,
                render={"voice": manifest.get("voice"), "animation": manifest.get("animation"), "thumbnail": manifest.get("thumbnail"), "tiktok_post_id": manifest.get("tiktok_post_id")},
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
