from unittest.mock import patch

import pytest
import requests

from youtube_automation import script_writer
from youtube_automation.config import PipelineConfig


def _config():
    config = PipelineConfig.load()
    config.secrets.gemini_api_key = "test-key"
    return config


def _ok_response(args):
    response = requests.Response()
    response.status_code = 200
    response._content = _json_bytes({
        "candidates": [{"content": {"parts": [{"functionCall": {"name": "emit_topics", "args": args}}]}}],
    })
    return response


def _json_bytes(data):
    import json
    return json.dumps(data).encode("utf-8")


def _error_response(status_code, text="error"):
    response = requests.Response()
    response.status_code = status_code
    response._content = text.encode("utf-8")
    return response


# Regression test: a real scheduled run failed because a bare ReadTimeout
# (not an HTTP status code, so it never hit the old status-code-only retry
# check) propagated straight out of _call_gemini and killed the whole
# pipeline run instead of being retried like a 503 already was.
def test_20_minute_target_is_not_silently_capped_down():
    # Regression test: this was previously running successfully in
    # production at ~20 minutes before the scene-count/output-token caps
    # got left at values tuned for a temporarily-reduced ~7 minute target -
    # meaning config.yaml asking for 1200s would have silently produced a
    # much shorter script regardless, since suggested_scenes was capped at
    # 60 and max_output_tokens at 8000 (gemini-3.5-flash's real ceiling is
    # 65,536 - nowhere close to being reached at 20 minutes).
    target_words, suggested_scenes, max_output_tokens = script_writer._script_length_params(1200)
    assert target_words >= 2500, "20 minutes of narration should be at least ~2500 words"
    # ~25 words/scene is the intended per-scene pacing - the scene count
    # cap must not force scenes far longer than that at this duration.
    assert suggested_scenes >= target_words / 30
    # Real headroom under gemini-3.5-flash's actual 65,536-token ceiling,
    # not silently clamped back down to a value tuned for a shorter script.
    assert max_output_tokens >= round(target_words * 3)


def test_short_targets_still_get_a_sensible_minimum_scene_count():
    _target_words, suggested_scenes, _max_tokens = script_writer._script_length_params(60)
    assert suggested_scenes >= 6


def test_call_gemini_retries_on_read_timeout_then_succeeds():
    config = _config()
    ok = _ok_response({"topics": ["a"]})
    with patch("youtube_automation.script_writer.time.sleep"), \
         patch("requests.post", side_effect=[requests.exceptions.ReadTimeout("timed out"), ok]) as post:
        result = script_writer._call_gemini("prompt", "emit_topics", {}, config, max_output_tokens=100)
    assert result == {"topics": ["a"]}
    assert post.call_count == 2


def test_call_gemini_retries_on_503_then_succeeds():
    config = _config()
    ok = _ok_response({"topics": ["a"]})
    with patch("youtube_automation.script_writer.time.sleep"), \
         patch("requests.post", side_effect=[_error_response(503), ok]) as post:
        result = script_writer._call_gemini("prompt", "emit_topics", {}, config, max_output_tokens=100)
    assert result == {"topics": ["a"]}
    assert post.call_count == 2


def test_call_gemini_raises_after_exhausting_retries_on_persistent_timeout():
    config = _config()
    with patch("youtube_automation.script_writer.time.sleep"), \
         patch("requests.post", side_effect=requests.exceptions.ReadTimeout("timed out")) as post:
        with pytest.raises(RuntimeError, match="timed out"):
            script_writer._call_gemini("prompt", "emit_topics", {}, config, max_output_tokens=100)
    assert post.call_count == script_writer._MAX_RETRIES + 1
