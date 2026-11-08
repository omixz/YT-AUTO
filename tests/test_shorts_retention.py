"""Shorts retention upgrades: tighten overlong Shorts, and no end card on daily Shorts (seamless loop)."""
import youtube_automation.script_writer as sw
from youtube_automation.config import PipelineConfig


def _data(words_per_scene, n=6):
    scenes = [{"role": "hook", "narration": "Three men vanished from a locked island. " + "x " * (words_per_scene - 7), "visual_keywords": ["a"]}]
    scenes += [{"role": "build", "narration": "y " * words_per_scene, "visual_keywords": ["a"]} for _ in range(n - 2)]
    scenes += [{"role": "insight", "narration": "z " * words_per_scene, "visual_keywords": ["a"]}]
    return {"title": "Orig", "description": "d", "tags": ["t"], "scenes": scenes}


def _cfg(fmt="shorts"):
    cfg = PipelineConfig.load()
    cfg.video.format = fmt
    return cfg


def test_overlong_short_is_tightened_and_keeps_title(monkeypatch):
    seen = {}

    def fake(prompt, fn, schema, config, max_tokens):
        seen["prompt"] = prompt
        cut = _data(25, n=4)
        cut["title"] = "Changed by model"
        return cut

    monkeypatch.setattr(sw, "_call_gemini", fake)
    out = sw._tighten_short(_data(40), 100, _cfg(), 4000)        # 240 words vs a 100-word budget
    assert sum(len(s["narration"].split()) for s in out["scenes"]) == 100
    assert out["title"] == "Orig"
    assert "loop back to the opening" in seen["prompt"]


def test_teaser_tighten_never_asks_for_a_loop(monkeypatch):
    seen = {}
    monkeypatch.setattr(sw, "_call_gemini", lambda prompt, *a: seen.setdefault("p", prompt) and _data(25, n=4))
    sw._tighten_short(_data(40), 100, _cfg("teaser"), 4000)
    assert "loop back" not in seen["p"] and "cliffhanger" in seen["p"]


def test_short_within_budget_is_untouched(monkeypatch):
    monkeypatch.setattr(sw, "_call_gemini", lambda *a: (_ for _ in ()).throw(AssertionError("no call expected")))
    data = _data(18)    # 108 words, inside 100 * 1.2
    assert sw._tighten_short(data, 100, _cfg(), 4000) is data


def test_bad_or_failed_tighten_keeps_original(monkeypatch):
    data = _data(40)
    monkeypatch.setattr(sw, "_call_gemini", lambda *a: _data(5, n=4))        # cut far below the length floor
    assert sw._tighten_short(data, 100, _cfg(), 4000) is data
    monkeypatch.setattr(sw, "_call_gemini", lambda *a: (_ for _ in ()).throw(RuntimeError("503")))
    assert sw._tighten_short(data, 100, _cfg(), 4000) is data
