import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

skia = pytest.importorskip("skia")

from youtube_automation.script_writer import Scene
from youtube_automation.toon import audio, direction, engine, render


def _sc(text, kw, role="build"):
    return Scene(text, kw, role)


def test_direction_maps_scene_meaning():
    scenes = [_sc("Nobody knows why the ship vanished at midnight?", ["ship"], "hook"),
              _sc("The viking raiders fought a bloody duel.", ["viking", "fight"]),
              _sc("And that is the lesson.", ["city"], "insight")]
    d = direction.direct(scenes, [4.0, 4.0, 4.0])
    assert d[0].camera == "push_in" and d[0].tod == "night" and any(k == "?" for _, k in d[0].emotes)
    assert d[1].action == "fight" and d[1].mood == "serious"
    assert d[2].camera == "pull_out" and any(k == "bulb" for _, k in d[2].emotes) and d[2].mascot


def test_envelope_fallback_and_beats():
    env = audio.envelope(None, 24, 48)
    assert env.shape == (48,) and 0 <= env.min() and env.max() <= 1
    import numpy as np
    e = np.concatenate([np.ones(10), np.zeros(12), np.ones(10)])
    assert audio.sentence_beats(e, 24, min_gap=0.2) == [22 / 24]


def test_every_archetype_draws_pixels():
    from youtube_automation import procedural_illustration as P
    from youtube_automation.toon import character as C
    import random
    for name in P._CHARACTER_ARCHETYPES:
        s = skia.Surface(200, 200)
        c = s.getCanvas()
        c.clear(skia.ColorWHITE)
        C.draw_character(c, C.Look.from_archetype(name, P._CHARACTER_ARCHETYPES, random.Random(1)),
                         C.pose_talk(1.0, 0.5), C.Face(mouth=0.5), 100, 190, 1.6, 1)
        assert s.makeImageSnapshot().toarray().std() > 5, name


def test_render_scene_makes_valid_clip(tmp_path):
    d = direction.direct([_sc("A pharaoh in a temple.", ["pharaoh", "temple"])], [1.0])[0]
    out = engine.render_scene(d, 1.0, 320, 180, 12, tmp_path / "s.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames,width", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert probe.strip().split(",") == ["320", "12"]


def test_failed_scene_falls_back_to_legacy(tmp_path, monkeypatch):
    cfg = SimpleNamespace(video=SimpleNamespace(resolution=(320, 180)), animation=SimpleNamespace(fps=12, toon_workers=1, toon_budget_seconds=60))
    monkeypatch.setattr(render, "_render_job", lambda job: (_ for _ in ()).throw(RuntimeError("boom")))
    used = []
    monkeypatch.setattr(render, "_legacy_clip", lambda *a: used.append(a[1]) or tmp_path / "legacy.mp4")
    paths = render.generate_all_clips([_sc("x", ["castle"]), _sc("y", ["ship"])], [1.0, 1.0], cfg, tmp_path, workers=1)
    assert used == [0, 1] and len(paths) == 2


def test_multi_worker_pool_path_renders_every_scene(tmp_path):
    """Regression: the process-pool branch crashed after rendering (swapped future/index), which made
    the pipeline silently discard all toon clips. Exercise it for real with 2 spawn workers."""
    cfg = SimpleNamespace(video=SimpleNamespace(resolution=(320, 180)), animation=SimpleNamespace(fps=12, toon_workers=2, toon_budget_seconds=120))
    scenes = [_sc(f"A knight marches {i}.", ["knight"]) for i in range(3)]
    paths = render.generate_all_clips(scenes, [1.0] * 3, cfg, tmp_path, workers=2)
    assert [p.name for p in paths] == [f"toon_scene_{i:02d}.mp4" for i in range(3)]
    assert render.LAST_STATS["fallback_scenes"] == 0 and render.LAST_STATS["scenes"] == 3
