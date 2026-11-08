"""Regression tests for the bugs fixed after the 2026-11-04..06 longform failures."""
import datetime as dt
import json
from unittest.mock import patch

import requests

import youtube_automation.script_writer as sw
from youtube_automation import growth_ledger, niche_selector, youtube_uploader
from youtube_automation.config import PipelineConfig


def _resp(data):
    r = requests.Response()
    r.status_code = 200
    r._content = json.dumps(data).encode("utf-8")
    return r


def _scene(role, words):
    return {"role": role, "narration": " ".join(f"w{i}" for i in range(words)), "visual_keywords": ["a"]}


def test_longform_token_budget_covers_the_json_overhead():
    words, _, tokens = sw._script_length_params(1200, 155)
    # 12,900 tokens (4/word) is exactly where the real runs hit MAX_TOKENS.
    assert tokens >= words * 8
    assert tokens <= sw._MODEL_MAX_OUTPUT_TOKENS


def test_call_gemini_escalates_budget_on_max_tokens():
    cfg = PipelineConfig.load()
    cfg.secrets.gemini_api_key = "k"
    truncated = _resp({"candidates": [{"content": {}, "finishReason": "MAX_TOKENS"}]})
    ok = _resp({"candidates": [{"content": {"parts": [{"functionCall": {"name": "emit_topics", "args": {"x": 1}}}]}}]})
    with patch("requests.post", side_effect=[truncated, ok]) as post:
        assert sw._call_gemini("p", "emit_topics", {}, cfg, max_output_tokens=1000) == {"x": 1}
    assert post.call_args_list[1].kwargs["json"]["generationConfig"]["maxOutputTokens"] == 2000


def test_failed_length_retry_keeps_the_first_draft(monkeypatch):
    cfg = PipelineConfig.load()
    cfg.video.target_seconds = 1200
    calls = {"full": 0}

    def fake(prompt, fn, params, config, max_tokens):
        if fn == sw.EMIT_EXTRA_SCENES:
            raise RuntimeError("503")
        calls["full"] += 1
        if calls["full"] > 1:
            raise RuntimeError("Gemini did not call emit_script: MAX_TOKENS")
        return {"title": "T", "description": "d", "tags": ["a"],
                "scenes": [_scene("hook", 100), _scene("build", 500), _scene("insight", 100)]}

    monkeypatch.setattr(sw, "_call_gemini", fake)
    script = sw.generate_script("topic", cfg)   # used to raise and kill the whole run
    assert len(script.scenes) == 3


def test_clean_tags_respects_youtube_500_char_limit():
    tags = [f"some long tag number {i}" for i in range(60)] + ["<bad>", "A", "a"]
    out = youtube_uploader.clean_tags(tags)
    cost = sum(len(t) + (2 if " " in t else 0) for t in out) + max(0, len(out) - 1)
    assert cost <= 500
    assert all("<" not in t and ">" not in t for t in out)
    assert len([t for t in out if t.lower() == "a"]) == 1


def test_clean_title_and_description_strip_angle_brackets():
    assert youtube_uploader.clean_title("A <b>bold</b> claim " + "x" * 200).startswith("A bbold/b claim")
    assert len(youtube_uploader.clean_title("x" * 200)) == 100
    assert len(youtube_uploader.clean_description("é" * 5000).encode("utf-8")) <= 5000


def test_seasonal_multiplier_matches_plural_niche_keys():
    assert niche_selector._seasonal_multiplier("world_wars", 6) == 1.3       # "wars" -> "war"
    assert niche_selector._seasonal_multiplier("dark_history", 1) == 1.3
    assert niche_selector._seasonal_multiplier("unsolved_mysteries", 6) == 1.0   # no data: neutral


def test_needs_audience_retries_a_failed_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    old = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    (tmp_path / "config").mkdir()
    (tmp_path / growth_ledger.LEDGER_PATH).write_text(json.dumps([
        {"video_id": "v1", "published_at": old, "privacy_status": "public", "avg_view_pct": None, "views": 3},
        {"video_id": "v2", "published_at": old, "privacy_status": "public", "avg_view_pct": 41.0, "views": 3},
    ]))
    ids = [r["video_id"] for r in growth_ledger.needs_audience(PipelineConfig.load())]
    assert ids == ["v1"]
