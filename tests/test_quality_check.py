import subprocess

import pytest

from youtube_automation import quality_check
from youtube_automation.config import PipelineConfig
from youtube_automation.script_writer import Scene, Script
from youtube_automation.tts import SceneAudio


def _config():
    return PipelineConfig.load()


# --- check() (script-level) -------------------------------------------------

def _script(word_count=200, n_scenes=8, first_role="hook", last_role="insight"):
    words_per_scene = max(1, word_count // n_scenes)
    scenes = [
        Scene(narration=" ".join(["word"] * words_per_scene), visual_keywords=["x"], role="build")
        for _ in range(n_scenes)
    ]
    if scenes:
        scenes[0].role = first_role
        scenes[-1].role = last_role
    return Script(topic="t", title="Title", description="d", tags=["t"], scenes=scenes)


def test_check_passes_a_well_formed_script():
    passed, reasons = quality_check.check(_script(), _config())
    assert passed and reasons == []


def test_check_fails_on_too_few_words():
    passed, reasons = quality_check.check(_script(word_count=10), _config())
    assert not passed
    assert any("words of narration" in r for r in reasons)


def test_check_fails_on_missing_hook():
    passed, reasons = quality_check.check(_script(first_role="build"), _config())
    assert not passed
    assert any("hook" in r for r in reasons)


# --- check_media() (rendered-file level) ------------------------------------

def _make_clip(path, duration=3.0, w=640, h=360, fps=30, with_audio=True, audio_freq=440, audio_gain=1.0):
    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={w}x{h}:r={fps}:d={duration}"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={audio_freq}:duration={duration}"]
        args += ["-af", f"volume={audio_gain}", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)]
    else:
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, capture_output=True, check=True)


def _scene_audio(duration):
    return [SceneAudio(scene_index=0, audio_path="unused", duration=duration, cues=[])]


def test_check_media_passes_a_correct_render(tmp_path):
    config = _config()
    config.video.format = "shorts"
    w, h = config.video.resolution
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=3.0, w=w, h=h, with_audio=True)
    captions = tmp_path / "captions.ass"
    captions.write_text("Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hello", encoding="utf-8")

    passed, reasons = quality_check.check_media(video, _scene_audio(3.0), captions, config)
    assert passed, reasons


def test_check_media_fails_on_missing_audio_stream(tmp_path):
    config = _config()
    config.video.format = "shorts"
    w, h = config.video.resolution
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=3.0, w=w, h=h, with_audio=False)

    passed, reasons = quality_check.check_media(video, _scene_audio(3.0), None, config)
    assert not passed
    assert any("no audio stream" in r for r in reasons)


def test_check_media_fails_on_near_silent_audio(tmp_path):
    config = _config()
    config.video.format = "shorts"
    w, h = config.video.resolution
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=3.0, w=w, h=h, with_audio=True, audio_gain=0.00001)

    passed, reasons = quality_check.check_media(video, _scene_audio(3.0), None, config)
    assert not passed
    assert any("effectively silent" in r for r in reasons)


def test_check_media_fails_on_wrong_resolution(tmp_path):
    config = _config()
    config.video.format = "shorts"
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=3.0, w=320, h=240, with_audio=True)

    passed, reasons = quality_check.check_media(video, _scene_audio(3.0), None, config)
    assert not passed
    assert any("resolution" in r for r in reasons)


def test_check_media_fails_on_truncated_duration(tmp_path):
    config = _config()
    config.video.format = "shorts"
    w, h = config.video.resolution
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=2.0, w=w, h=h, with_audio=True)

    # Expected duration is far longer than the 2s clip actually rendered.
    passed, reasons = quality_check.check_media(video, _scene_audio(30.0), None, config)
    assert not passed
    assert any("doesn't match expected" in r for r in reasons)


def test_check_media_fails_on_wrong_frame_rate(tmp_path):
    config = _config()
    config.video.format = "shorts"
    w, h = config.video.resolution
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=3.0, w=w, h=h, fps=10, with_audio=True)

    passed, reasons = quality_check.check_media(video, _scene_audio(3.0), None, config)
    assert not passed
    assert any("frame rate" in r for r in reasons)


def test_check_media_fails_on_missing_file(tmp_path):
    passed, reasons = quality_check.check_media(tmp_path / "nope.mp4", _scene_audio(3.0), None, _config())
    assert not passed
    assert any("missing or empty" in r for r in reasons)


def test_check_media_fails_on_empty_captions(tmp_path):
    config = _config()
    config.video.format = "shorts"
    w, h = config.video.resolution
    video = tmp_path / "final.mp4"
    _make_clip(video, duration=3.0, w=w, h=h, with_audio=True)
    captions = tmp_path / "captions.ass"
    captions.write_text("[Script Info]\nno dialogue here\n", encoding="utf-8")

    passed, reasons = quality_check.check_media(video, _scene_audio(3.0), captions, config)
    assert not passed
    assert any("no caption lines" in r for r in reasons)
