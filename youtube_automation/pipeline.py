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
from .config import ROOT, VERTICAL_FORMATS, PipelineConfig
from .script_writer import generate_script
from .tts import SceneAudio
from .visuals import VisualAsset

logger = logging.getLogger(__name__)

KEEP_FILES = {"final.mp4", "thumbnail.jpg", "captions.ass", "manifest.json"}


def _select_niche_and_format(config: PipelineConfig, format_override: Optional[str] = None,
                             niche_key: Optional[str] = None) -> tuple:
    """Picks (niche_key, format_name) and mutates config in place so every
    other module (script_writer, branding, quality_check, assembler, ...)
    just keeps reading config.channel.niche / config.video.format like
    before - see ChannelConfig.niche / VideoConfig.format docstrings."""
    if format_override == "teaser":
        # Teasers are never bandit-picked: the format is forced and the niche is whichever niche the promoted longform is in.
        format_name = "teaser"
        niche_key = niche_key or niche_selector.choose(config, format_override="shorts")[0]
    else:
        niche_key, format_name = niche_selector.choose(config, format_override=format_override)
    niche = next(n for n in config.niches if n.key == niche_key)

    config.channel.niche = niche.niche
    config.channel.audience = niche.audience or config.channel.audience
    config.channel.tone = niche.tone or config.channel.tone

    config.video.format = format_name
    config.video.target_seconds = config.video.formats[format_name].target_seconds
    config.visuals.orientation = "portrait" if format_name in VERTICAL_FORMATS else "landscape"

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
                                                   title=script.title, scene_audio=content_scene_audio,
                                                   characters=getattr(script, "characters", None))
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


def _over_daily_cap(config: PipelineConfig, format_name: str, public_today: int, attempts_today: int) -> bool:
    """daily_cap public uploads per format per UTC day; one extra attempt is allowed so a gate-failed run can retry."""
    fmt = config.video.formats.get(format_name)
    cap = max(1, int(getattr(fmt, "daily_cap", 1) or 1))
    return public_today >= cap or attempts_today >= cap + 1


def discovery_hashtags(niche_key: str, format_name: str) -> str:
    """3 hashtags for the description (YouTube shows the first 3 above the title and indexes them for search/browse).
    #Shorts first on vertical formats - it is the Shorts-feed discovery tag."""
    niche_tag = "#" + "".join(w.capitalize() for w in niche_key.split("_"))
    tags = (["#Shorts"] if format_name in VERTICAL_FORMATS else []) + [niche_tag, "#History", "#Documentary"]
    return " ".join(list(dict.fromkeys(tags))[:3])


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
    force: bool = False,
) -> dict:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    work_dir = ROOT / "output" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    teaser_source = None
    if format_override == "teaser":
        # Cheapest checks first (no Gemini/render cost): daily cap, then is there a longform worth promoting?
        if not (force or dry_run or topic_override):
            public_today, attempts_today = growth_ledger.daily_counts("teaser")
            if _over_daily_cap(config, "teaser", public_today, attempts_today):
                logger.warning("Daily cap: %d public / %d attempt(s) of teaser already today - skipping (use --force to override).", public_today, attempts_today)
                return {"skipped": "daily_cap", "format": "teaser", "public_today": public_today, "attempts_today": attempts_today}
        teaser_source = growth_ledger.pick_teaser_source(config.teaser.window_days, config.teaser.min_age_hours)
        if teaser_source is None and not topic_override:
            logger.warning("No public longform from the last %d days is waiting for a teaser - skipping this run.", config.teaser.window_days)
            return {"skipped": "no_longform_to_tease", "format": "teaser"}
        niche_key, format_name = _select_niche_and_format(config, "teaser", niche_key=(teaser_source or {}).get("niche"))
        logger.info("Teaser for longform %s: %s", (teaser_source or {}).get("video_id"), (teaser_source or {}).get("title"))
    else:
        niche_key, format_name = _select_niche_and_format(config, format_override=format_override)
    if format_name != "teaser" and not (force or dry_run or topic_override):
        # One Short and one longform per day: skip if a public one already went up today, or two attempts were already
        # made (a gate-failed private upload may be retried once). Costs nothing: no Gemini calls happen before this.
        public_today, attempts_today = growth_ledger.daily_counts(format_name)
        if _over_daily_cap(config, format_name, public_today, attempts_today):
            logger.warning("Daily cap: %d public / %d attempt(s) of %s already today - skipping this run (use --force to override).",
                           public_today, attempts_today, format_name)
            return {"skipped": "daily_cap", "format": format_name, "public_today": public_today, "attempts_today": attempts_today}
    logger.info("Selected niche=%s format=%s", niche_key, format_name)

    logger.info("Picking topic...")
    if teaser_source and not topic_override:
        # A teaser retells an existing longform's story: do NOT consume the niche's topic queue/history.
        topic = teaser_source.get("topic") or teaser_source["title"]
    else:
        topic = topic_store.next_topic(config, niche_key, override=topic_override)
    logger.info("Topic: %s", topic)

    max_attempts = max(1, int(config.quality.max_script_attempts))
    hook_warns: list = []
    for attempt in range(1, max_attempts + 1):
        logger.info("Writing script (attempt %d/%d)...", attempt, max_attempts)
        script = generate_script(topic, config, source=teaser_source)
        logger.info("Title: %s (%d scenes)", script.title, len(script.scenes))
        # Script-level checks run now (cheap, before spending render time); media-level checks
        # (below, after the video is built) join the same final verdict - see quality_check.py.
        script.title = quality_check.soften_title(quality_check.pick_best_title(script))
        if format_name == "teaser" and quality_check.ensure_teaser_cta(script, config.teaser.cta):
            logger.info("Teaser's last scene had no 'full story' call-to-action; appended it.")
        hook_warns = quality_check.hook_warnings(script)
        if hook_warns:
            logger.warning("Weak hook: %s", "; ".join(hook_warns))
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

    # No channel-branded intro card - the video opens directly on content.
    outro_visual = outro_audio = None
    if format_name == "shorts":
        # No end card on daily Shorts: the last line loops back to the first, and a static 2s "Subscribe" card
        # breaks that seamless replay (loops/rewatches are what push a Short in the feed). Teasers keep their
        # "Full story" card - pointing at the longform is their whole job.
        logger.info("Shorts: no outro card (seamless loop).")
    elif format_name == "teaser" and teaser_source:
        logger.info("Building outro...")
        outro_visual, outro_audio = branding.build_outro(config, work_dir, duration=2.5, heading="Full story", cta=teaser_source["title"])
    else:
        logger.info("Building outro...")
        outro_visual, outro_audio = branding.build_outro(config, work_dir)

    if outro_audio is not None:
        all_scene_audio = content_scene_audio + [outro_audio]
        all_visuals = content_visuals + [outro_visual]
        narration_path = tts.concat_audio(
            [content_narration_path, outro_audio.audio_path],
            work_dir / "narration_final.mp3",
        )
    else:
        all_scene_audio, all_visuals, narration_path = list(content_scene_audio), list(content_visuals), content_narration_path
    outro_seconds = outro_audio.duration if outro_audio is not None else 0.0

    logger.info("Building captions...")
    on_screen_texts = [s.on_screen_text for s in script.scenes] + ([""] if outro_audio is not None else [])
    ass_path = subtitles.build_ass(
        all_scene_audio, work_dir / "captions.ass", config.video.resolution,
        on_screen_texts=on_screen_texts, position=config.video.subtitle_position,
    )

    logger.info("Building ambient sound effects...")
    ambience_path = sound_effects.build_ambience_track(
        script.scenes, content_scene_audio, 0.0, outro_seconds, work_dir,
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
    scene_roles = [s.role for s in script.scenes] + (["build"] if outro_audio is not None else [])
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
                                               work_dir / "thumbnail.jpg", script.thumbnail_text,
                                               characters=getattr(script, "characters", None))
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
        "hook_warnings": hook_warns,
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
        # An explicit --publish-at must not apply to a gate-failed video either: the uploader turns publishAt into
        # "private now, PUBLIC at that time", which would auto-release exactly the video a human was meant to review.
        effective_publish_at = publish_at if passed_quality_gate else None
        if publish_at and not passed_quality_gate:
            logger.warning("Ignoring publish_at=%s: the quality gate failed, so this video stays %s for review.",
                           publish_at, effective_privacy)
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
        related = growth_ledger.related_videos(niche_key, "longform", n=2)
        if format_name == "teaser" and teaser_source:
            # The point of this Short: send viewers to the longform. Put it first, as a link and as an exact search.
            description += f"\n\n\u25B6 Watch the full story: https://youtu.be/{teaser_source['video_id']}\nSearch YouTube for: {teaser_source['title']}"
            related = []
        if related:
            description += "\n\nWatch next:\n" + "\n".join(f"\u25B6 {r['title']} - https://youtu.be/{r['video_id']}" for r in related)
        if "#" not in description:
            description += "\n\n" + discovery_hashtags(niche_key, format_name)
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
            if format_name not in VERTICAL_FORMATS:
                logger.error(
                    "Direct YouTube upload failed (%s) - not attempting the Buffer fallback, since Buffer's "
                    "YouTube integration only supports Shorts and this run is '%s'.", exc, format_name,
                )
                raise

            logger.warning("Direct YouTube upload failed (%s) - trying the Buffer fallback...", exc)
            video_url = media_host.upload_public(video_path, f"{run_id}.mp4", config)
            buffer_post_id = buffer_publisher.publish_video(
                video_url, script.title, description, config, publish_at=effective_publish_at,
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
            if teaser_source:
                manifest["teaser_for"] = teaser_source["video_id"]
            manifest["youtube_url"] = f"https://youtu.be/{video_id}"
            manifest["privacy_status"] = effective_privacy
            manifest["publish_at"] = effective_publish_at
            manifest["published_via"] = "youtube_api"
            tiktok_id = crosspost.tiktok(config, format_name=format_name, privacy=effective_privacy, passed_gate=passed_quality_gate,
                                         dry_run=dry_run, video_path=video_path, run_id=run_id, title=script.title,
                                         video_id=video_id,
                                         search_phrase=(teaser_source["title"] if teaser_source else search_phrase))
            if tiktok_id:
                manifest["tiktok_post_id"] = tiktok_id

            growth_ledger.record_published(
                niche_key, format_name, video_id, title=script.title, topic=topic,
                privacy_status=effective_privacy, passed_quality_gate=passed_quality_gate,
                quality_gate_reasons=quality_reasons,
                seed=(" ".join(sc.narration for sc in script.scenes[:5])[:700] if format_name == "longform" else ""),
                teaser_for=(teaser_source["video_id"] if teaser_source else None),
                render={"voice": manifest.get("voice"), "animation": manifest.get("animation"), "thumbnail": manifest.get("thumbnail"), "tiktok_post_id": manifest.get("tiktok_post_id"), "hook_warnings": manifest.get("hook_warnings")},
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
