import youtube_automation.script_writer as sw
from youtube_automation.config import PipelineConfig


def _scene(role, words):
    return {"role": role, "narration": " ".join([f"w{i}" for i in range(words)]), "visual_keywords": ["a"]}


def test_short_script_is_topped_up_to_the_unchanged_length_bar(monkeypatch):
    cfg = PipelineConfig.load()
    cfg.video.target_seconds = 1200
    target_words, _, _ = sw._script_length_params(1200)
    bar = round(target_words * sw.MIN_TARGET_LENGTH_FRACTION)
    calls = {"full": 0, "extra": 0}

    def fake(prompt, fn, params, config, max_tokens):
        if fn == sw.EMIT_EXTRA_SCENES:
            calls["extra"] += 1
            return {"scenes": [{**_scene("build", 200), "narration": f"extra{calls['extra']} " + " ".join(["y"] * 200) + f" k{j}"} for j in range(5)]}
        calls["full"] += 1
        scenes = [_scene("hook", 150)] + [_scene("build", 150) for _ in range(8)] + [_scene("insight", 150)]
        return {"title": "T", "description": "d " * 10, "tags": ["a", "b", "c"], "scenes": scenes}

    monkeypatch.setattr(sw, "_call_gemini", fake)
    script = sw.generate_script("topic", cfg)
    words = len(script.full_narration.split())
    assert words >= bar, (words, bar)
    assert script.scenes[0].role == "hook" and script.scenes[-1].role == "insight"
    assert calls["extra"] >= 1


def test_failed_extension_keeps_the_script(monkeypatch):
    cfg = PipelineConfig.load()
    cfg.video.target_seconds = 1200

    def fake(prompt, fn, params, config, max_tokens):
        if fn == sw.EMIT_EXTRA_SCENES:
            raise RuntimeError("quota")
        return {"title": "T", "description": "d " * 10, "tags": ["a", "b", "c"],
                "scenes": [_scene("hook", 100), _scene("build", 100), _scene("insight", 100)]}

    monkeypatch.setattr(sw, "_call_gemini", fake)
    script = sw.generate_script("topic", cfg)
    assert len(script.scenes) == 3
