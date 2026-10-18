import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("soundfile")

from youtube_automation import kokoro_tts, tts
from youtube_automation.config import VoiceConfig


class _Tok:
    def __init__(self, text, a, b):
        self.text, self.start_ts, self.end_ts = text, a, b


class _Item:
    def __init__(self, text, secs):
        self.graphemes = text
        self.audio = np.sin(np.linspace(0, 440 * secs, int(24000 * secs))).astype(np.float32) * 0.2
        words = text.split()
        self.tokens = [_Tok(w, i * secs / len(words), (i + 1) * secs / len(words)) for i, w in enumerate(words)]


def _install_fake_kokoro(monkeypatch):
    mod = types.ModuleType("kokoro")

    class KPipeline:
        def __init__(self, lang_code="a"):
            self.lang = lang_code

        def __call__(self, text, voice, speed):
            self.speed = speed
            yield _Item("first sentence here", 0.5)
            yield _Item("second one follows", 0.4)

    mod.KPipeline = KPipeline
    monkeypatch.setitem(sys.modules, "kokoro", mod)
    kokoro_tts._PIPELINES.clear()


def test_kokoro_writes_mp3_and_word_cues(tmp_path, monkeypatch):
    _install_fake_kokoro(monkeypatch)
    out = tmp_path / "s.mp3"
    cues = kokoro_tts.synthesize_one("first sentence here second one follows", VoiceConfig(provider="kokoro", name="am_michael"), out, "insight")
    assert out.exists() and out.stat().st_size > 1000
    assert [c[0] for c in cues] == "first sentence here second one follows".split()
    assert all(b >= a for (_, a, b) in cues) and cues[3][1] >= 0.5      # 2nd chunk starts after the 1st + gap
    assert kokoro_tts._PIPELINES["a"].speed == pytest.approx(0.93)       # insight is slowed


def test_rate_multiplier():
    assert kokoro_tts._rate_multiplier("-10%") == pytest.approx(0.9)
    assert kokoro_tts._rate_multiplier("garbage") == 1.0


def test_kokoro_failure_falls_back_to_edge_for_whole_video(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(kokoro_tts, "synthesize_one", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model download failed")))
    monkeypatch.setattr(tts, "_synthesize_one_with_retry", lambda text, voice, out, role="build": calls.append(voice.provider) or [])
    monkeypatch.setattr(tts, "_probe_duration", lambda p: 1.0)
    monkeypatch.setattr(tts, "concat_audio", lambda paths, out: out)
    script = SimpleNamespace(scenes=[SimpleNamespace(narration="a b", role="hook"), SimpleNamespace(narration="c d", role="build")])
    scenes, _ = tts.synthesize_script(script, VoiceConfig(provider="kokoro", name="am_michael"), tmp_path)
    assert calls == ["edge-tts", "edge-tts"] and len(scenes) == 2        # every scene re-done with ONE consistent voice


def test_config_defaults_are_backward_compatible():
    from youtube_automation.config import QualityConfig
    q = QualityConfig()
    assert q.max_script_attempts == 3 and q.on_gate_failure == "private"
