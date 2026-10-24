"""Drop-in replacement for procedural_illustration.generate_all_clips.

Renders one MP4 per scene in parallel worker processes. It can never make a run
worse than the legacy engine: any scene that errors, exceeds the time budget or
produces a bad file is re-rendered by the legacy renderer instead."""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)
LAST_STATS: dict = {}   # read by pipeline.py into the run manifest / report


def _render_job(args) -> str:
    # Imported inside the worker so the parent never initialises skia (spawn-safe).
    from .engine import render_scene
    direction, duration, w, h, fps, out_path, audio_path = args
    render_scene(direction, duration, w, h, fps, Path(out_path), Path(audio_path) if audio_path else None)
    return str(out_path)


def _clip_ok(path: Path, duration: float) -> bool:
    if not path.exists() or path.stat().st_size < 2000:
        return False
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        return float(out) >= duration - 0.25
    except Exception:
        return False


def _legacy_clip(scenes, i, config, work_dir, durations, title) -> Path:
    from .. import procedural_illustration as P
    fallback = P._dominant_subject(scenes, extra_text=title)
    settings = P._resolve_settings_for_video(scenes)
    return P.generate_scene_clip(scenes[i], i, config, work_dir, durations[i], subject_fallback=fallback, forced_setting=settings[i])


def generate_all_clips(scenes, durations: List[float], config, work_dir: Path, title: str = "",
                       scene_audio: Optional[list] = None, workers: Optional[int] = None) -> List[Path]:
    from . import direction

    work_dir = Path(work_dir)
    w, h = config.video.resolution
    fps = int(config.animation.fps)
    dirs = direction.direct(scenes, durations, title)
    audio = [getattr(a, "audio_path", None) for a in (scene_audio or [])]
    audio += [None] * (len(scenes) - len(audio))
    from dataclasses import replace
    from . import callouts as _callouts
    for i, a in enumerate(scene_audio or []):
        if i < len(dirs) and getattr(a, "cues", None):
            dirs[i] = replace(dirs[i], callouts=_callouts.extract(a.cues, durations[i]))
    outs = [work_dir / f"toon_scene_{i:02d}.mp4" for i in range(len(scenes))]
    jobs = [(dirs[i], durations[i], w, h, fps, str(outs[i]), str(audio[i]) if audio[i] else None) for i in range(len(scenes))]

    if workers is None:
        configured = int(getattr(config.animation, "toon_workers", 0) or 0)
        workers = configured or max(1, min(3, (os.cpu_count() or 1) - 1 or 1))
    budget = float(getattr(config.animation, "toon_budget_seconds", 2400))
    start = time.monotonic()
    failed: List[int] = []

    if workers <= 1:
        for i, job in enumerate(jobs):
            if time.monotonic() - start > budget:
                failed.append(i)
                continue
            try:
                _render_job(job)
            except Exception:
                logger.exception("toon render failed for scene %d", i)
                failed.append(i)
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
            futures = {pool.submit(_render_job, job): i for i, job in enumerate(jobs)}
            for fut in as_completed(futures):
                i = futures[fut]
                if time.monotonic() - start > budget:
                    for other in futures:
                        other.cancel()
                try:
                    fut.result()
                except Exception:
                    logger.exception("toon render failed for scene %d", i)
                    failed.append(i)
        failed += [i for f, i in futures.items() if f.cancelled() and i not in failed]

    paths: List[Path] = []
    for i in range(len(scenes)):
        if i in failed or not _clip_ok(outs[i], durations[i]):
            logger.warning("scene %d: falling back to legacy renderer", i)
            paths.append(_legacy_clip(scenes, i, config, work_dir, durations, title))
        else:
            paths.append(outs[i])
    LAST_STATS.clear()
    LAST_STATS.update(scenes=len(scenes), fallback_scenes=len(failed), seconds=round(time.monotonic() - start, 1), workers=workers)
    logger.info("toon: %d/%d scenes rendered in %.0fs (%d workers)", len(scenes) - len(failed), len(scenes),
                time.monotonic() - start, workers)
    return paths
