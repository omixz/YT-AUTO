import base64
import json
from unittest.mock import patch

import pytest
import requests

from youtube_automation import google_tts
from youtube_automation.config import VoiceConfig


def _voice():
    return VoiceConfig(provider="google", name="en-US-Neural2-D", rate="+0%", pitch="+0Hz")


def _fake_response(audio_bytes, timepoints):
    payload = {
        "audioContent": base64.b64encode(audio_bytes).decode("ascii"),
        "timepoints": timepoints,
    }
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode("utf-8")
    return response


def _real_silent_mp3(tmp_path, duration=1.0):
    import subprocess
    path = tmp_path / "silence.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(duration), str(path)],
        check=True, capture_output=True,
    )
    return path.read_bytes()


def test_synthesize_one_returns_word_cues_from_timepoints(tmp_path):
    audio_bytes = _real_silent_mp3(tmp_path)
    timepoints = [{"markName": "w0", "timeSeconds": 0.0}, {"markName": "w1", "timeSeconds": 0.5}]
    ok = _fake_response(audio_bytes, timepoints)

    out_path = tmp_path / "out.mp3"
    with patch("requests.post", return_value=ok):
        cues = google_tts.synthesize_one("hello world", _voice(), "test-key", out_path)

    assert out_path.exists() and out_path.read_bytes() == audio_bytes
    assert [c[0] for c in cues] == ["hello", "world"]
    assert cues[0] == ("hello", 0.0, 0.5)
    assert cues[1][1] == 0.5  # second word starts where timepoint said


def test_synthesize_one_sends_ssml_marks_and_rate_pitch(tmp_path):
    audio_bytes = b"ID3fakeaudio"
    ok = _fake_response(audio_bytes, [])
    voice = VoiceConfig(provider="google", name="en-US-Neural2-D", rate="+10%", pitch="+0Hz")
    with patch("requests.post", return_value=ok) as post, \
         patch.object(google_tts, "_probe_duration", return_value=1.0):
        google_tts.synthesize_one("hi there", voice, "test-key", tmp_path / "out.mp3")
    body = post.call_args.kwargs["json"]
    assert "<mark name=\"w0\"/>hi" in body["input"]["ssml"]
    assert "<mark name=\"w1\"/>there" in body["input"]["ssml"]
    assert body["audioConfig"]["speakingRate"] == pytest.approx(1.1)
    assert post.call_args.kwargs["params"] == {"key": "test-key"}


def test_synthesize_one_raises_on_api_error(tmp_path):
    err = requests.Response()
    err.status_code = 400
    err._content = b'{"error": "bad request"}'
    with patch("requests.post", return_value=err), patch("youtube_automation.google_tts.time.sleep"):
        with pytest.raises(RuntimeError, match="400"):
            google_tts.synthesize_one("hi", _voice(), "test-key", tmp_path / "out.mp3")


def test_parse_rate_and_pitch_defaults():
    assert google_tts._parse_rate("+0%") == 1.0
    assert google_tts._parse_rate("+20%") == pytest.approx(1.2)
    assert google_tts._parse_rate("-50%") == pytest.approx(0.5)
    assert google_tts._parse_pitch("+0Hz") == 0.0
