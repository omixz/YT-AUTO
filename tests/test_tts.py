from unittest.mock import patch

import pytest
import edge_tts

from youtube_automation import tts
from youtube_automation.config import VoiceConfig
from youtube_automation.tts import WordCue


def _voice():
    return VoiceConfig()


# Regression test: a real scheduled run crashed outright on
# edge_tts.exceptions.NoAudioReceived, a transient hiccup from edge-tts's
# free endpoint unrelated to the input text, with zero retry logic.
def test_synthesize_one_with_retry_retries_on_no_audio_received(tmp_path):
    calls = {"n": 0}

    def fake_run(coro):
        coro.close()
        calls["n"] += 1
        if calls["n"] == 1:
            raise edge_tts.exceptions.NoAudioReceived("no audio")
        return [WordCue(text="hi", start=0.0, end=0.5)]

    with patch("youtube_automation.tts.time.sleep"), \
         patch("youtube_automation.tts.asyncio.run", side_effect=fake_run):
        result = tts._synthesize_one_with_retry("hello", _voice(), tmp_path / "out.mp3")

    assert result == [WordCue(text="hi", start=0.0, end=0.5)]
    assert calls["n"] == 2


def test_synthesize_one_with_retry_raises_after_exhausting_retries(tmp_path):
    def fake_run(coro):
        coro.close()
        raise edge_tts.exceptions.NoAudioReceived("no audio")

    with patch("youtube_automation.tts.time.sleep"), \
         patch("youtube_automation.tts.asyncio.run", side_effect=fake_run) as run:
        with pytest.raises(RuntimeError, match="no audio"):
            tts._synthesize_one_with_retry("hello", _voice(), tmp_path / "out.mp3")

    assert run.call_count == tts._MAX_TTS_RETRIES + 1
