import wave

import numpy as np

from youtube_automation import sound_effects
from youtube_automation.script_writer import Scene
from youtube_automation.tts import SceneAudio


def _scene_audio(tmp_path, idx, seconds):
    # A tiny real WAV so build_ambience_track has a valid duration to work with.
    path = tmp_path / f"n{idx}.wav"
    sr = 44100
    pcm = (0.2 * np.sin(np.linspace(0, seconds * 200, int(sr * seconds)))).astype(np.float32)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((pcm * 32767).astype(np.int16).tobytes())
    return SceneAudio(scene_index=idx, audio_path=path, duration=seconds, cues=[])


def _rms(path):
    with wave.open(str(path)) as f:
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(float) / 32768
    return np.sqrt(np.mean(pcm ** 2))


def test_ambience_present_even_with_no_keyword_matches(tmp_path):
    # Topic with nothing the SFX matcher recognises - must still get a bed.
    scenes = [Scene(narration="An abstract idea about economics.", visual_keywords=["economy", "policy"])]
    audio = [_scene_audio(tmp_path, 0, 2.0)]
    path = sound_effects.build_ambience_track(scenes, audio, 0.0, 0.0, tmp_path)
    assert path is not None and path.exists()
    assert _rms(path) > 0.0  # not dead silence


def test_matched_scene_is_louder_than_the_air_default(tmp_path):
    audio = [_scene_audio(tmp_path, 0, 3.0)]
    # Separate dirs: build_ambience_track always writes "ambience.wav".
    d1 = tmp_path / "ocean"; d1.mkdir()
    d2 = tmp_path / "neutral"; d2.mkdir()
    ocean = sound_effects.build_ambience_track(
        [Scene(narration="Waves crash.", visual_keywords=["ocean", "wave"])], audio, 0.0, 0.0, d1)
    neutral = sound_effects.build_ambience_track(
        [Scene(narration="Economics.", visual_keywords=["economy"])], audio, 0.0, 0.0, d2)
    # A matched scene layers its specific SFX; it must be louder than the
    # barely-there neutral air bed an unmatched scene falls back to.
    assert _rms(ocean) > _rms(neutral)


def test_air_default_is_registered():
    assert "air" in sound_effects._SFX_SYNTH
