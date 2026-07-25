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


def test_resolve_synthesizer_uses_google_when_provider_and_key_set(tmp_path):
    voice = VoiceConfig(provider="google", name="en-US-Neural2-D")
    with patch("youtube_automation.tts.google_tts.synthesize_one",
               return_value=[("hi", 0.0, 0.5)]) as synth:
        synthesize_one = tts._resolve_synthesizer(voice, "test-key")
        cues = synthesize_one("hi", tmp_path / "out.mp3")
    synth.assert_called_once_with("hi", voice, "test-key", tmp_path / "out.mp3")
    assert cues == [WordCue(text="hi", start=0.0, end=0.5)]


def test_resolve_synthesizer_falls_back_to_edge_tts_when_key_missing(tmp_path):
    # Regression guard: switching config.voice.provider to "google" before
    # GOOGLE_TTS_API_KEY is configured must not break the run.
    voice = VoiceConfig(provider="google", name="en-US-Neural2-D")
    with patch("youtube_automation.tts._synthesize_one_with_retry",
               return_value=[WordCue(text="hi", start=0.0, end=0.5)]) as edge_synth, \
         patch("youtube_automation.tts.google_tts.synthesize_one") as google_synth:
        synthesize_one = tts._resolve_synthesizer(voice, None)
        synthesize_one("hi", tmp_path / "out.mp3")
    edge_synth.assert_called_once()
    google_synth.assert_not_called()


def test_resolve_synthesizer_fallback_swaps_to_valid_edge_tts_voice_name(tmp_path):
    # Regression guard: a real scheduled run crashed with
    # ValueError: Invalid voice 'en-US-Neural2-D' because the fallback path
    # reused the Google-only voice name verbatim instead of swapping to a
    # real edge-tts voice.
    voice = VoiceConfig(provider="google", name="en-US-Neural2-D")
    with patch("youtube_automation.tts._synthesize_one_with_retry",
               return_value=[]) as edge_synth:
        synthesize_one = tts._resolve_synthesizer(voice, None)
        synthesize_one("hi", tmp_path / "out.mp3")
    called_voice = edge_synth.call_args[0][1]
    assert called_voice.name == tts._EDGE_TTS_FALLBACK_VOICE
    assert called_voice.name != "en-US-Neural2-D"


def test_resolve_synthesizer_uses_edge_tts_by_default():
    voice = VoiceConfig()  # provider defaults to "edge-tts"
    with patch("youtube_automation.tts._synthesize_one_with_retry",
               return_value=[]) as edge_synth:
        synthesize_one = tts._resolve_synthesizer(voice, "unused-key")
        synthesize_one("hi", "out.mp3")
    edge_synth.assert_called_once()
