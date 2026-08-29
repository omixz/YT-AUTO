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


# Regression tests for a severe, silent bug: _apply_expressiveness used to
# wrap narration in hand-built SSML (<speak><prosody>...) and hand that
# whole string to edge_tts.Communicate() as its `text` argument.
# edge_tts.Communicate escapes and wraps *whatever text it receives*
# internally (see edge_tts.communicate.Communicate.__init__ -> mkssml(
# escape(text))) - it does not parse SSML out of the string you give it.
# The voice ended up literally speaking the raw markup
# ("less than speak version one point oh...") prepended/appended to every
# scene's real narration, in every video, silently (Communicate() doesn't
# raise on this - it "succeeds" with wrong audio), because the existing
# tests above all mock out asyncio.run entirely and never inspected what
# text/kwargs actually reached Communicate().

def test_apply_expressiveness_never_produces_xml_tags():
    text = "**Nobody** expected this,| and the city vanished.| The end."
    cleaned = tts._apply_expressiveness(text)
    assert "<" not in cleaned and ">" not in cleaned
    assert "**" not in cleaned
    assert "|" not in cleaned


def test_apply_expressiveness_strips_bold_markers_keeping_the_word():
    assert tts._apply_expressiveness("This is **shocking** news.") == "This is shocking news."


def test_apply_expressiveness_converts_breath_pauses_to_plain_punctuation():
    assert tts._apply_expressiveness("Wait,| what happened?") == "Wait, what happened?"
    assert tts._apply_expressiveness("It was over.| Nothing remained.") == "It was over. Nothing remained."


def test_prosody_kwargs_match_edge_tts_own_validation_format():
    # edge_tts.data_classes.TTSConfig validates rate/volume against
    # ^[+-]\d+%$ and pitch against ^[+-]\d+Hz$ - integers only, no "st"
    # (semitones) or "dB", which is what this table used to contain (would
    # have raised ValueError from edge_tts's own constructor had these
    # values ever actually reached it - they hadn't, since they only ever
    # existed inside the broken SSML text).
    import re
    rate_re = re.compile(r"^[+-]\d+%$")
    volume_re = re.compile(r"^[+-]\d+%$")
    pitch_re = re.compile(r"^[+-]\d+Hz$")
    for role in ("hook", "build", "insight", "some-unknown-role"):
        kwargs = tts._prosody_kwargs(role)
        assert rate_re.match(kwargs["rate"]), kwargs["rate"]
        assert volume_re.match(kwargs["volume"]), kwargs["volume"]
        assert pitch_re.match(kwargs["pitch"]), kwargs["pitch"]


def test_prosody_kwargs_layers_role_delta_on_top_of_voice_base():
    kwargs = tts._prosody_kwargs("hook", base_rate="+10%", base_pitch="+5Hz")
    assert kwargs["rate"] == "+25%"   # +10 base + 15 hook delta
    assert kwargs["pitch"] == "+25Hz"  # +5 base + 20 hook delta


def test_synthesize_one_passes_plain_text_and_valid_kwargs_to_communicate(tmp_path):
    # The actual end-to-end regression guard: mock edge_tts.Communicate
    # itself (not asyncio.run) and inspect exactly what it was called with.
    import asyncio

    captured = {}

    class FakeCommunicate:
        def __init__(self, text, voice_name, **kwargs):
            captured["text"] = text
            captured["kwargs"] = kwargs

        async def stream(self):
            if False:
                yield {}  # pragma: no cover - makes this an async generator

    with patch("youtube_automation.tts.edge_tts.Communicate", FakeCommunicate):
        asyncio.run(tts._synthesize_one("Sears & Roebuck **shocked** everyone,| overnight.",
                                          _voice(), tmp_path / "out.mp3", role="hook"))

    assert "<" not in captured["text"] and ">" not in captured["text"]
    assert "**" not in captured["text"] and "|" not in captured["text"]
    # The ampersand is real narration content, not markup - must survive
    # (it would have broken XML parsing under the old SSML approach; plain
    # text has no such restriction).
    assert "Sears & Roebuck" in captured["text"]
    assert captured["kwargs"]["rate"] == "+15%"
    assert captured["kwargs"]["pitch"] == "+20Hz"
    assert captured["kwargs"]["volume"] == "+10%"
