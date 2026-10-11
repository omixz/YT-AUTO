import shutil
import subprocess
from pathlib import Path

import pytest

from youtube_automation import cinematic
from youtube_automation.script_writer import Scene

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _scene(text, role="build", kw=()):
    return Scene(role=role, narration=text, visual_keywords=list(kw))


def test_look_matches_the_story_mood():
    assert cinematic.look_for_scene(_scene("A storm hit the harbour")).name == "storm"
    assert cinematic.look_for_scene(_scene("The army burned the city")).name == "danger"
    assert cinematic.look_for_scene(_scene("Snow covered the camp")).name == "cold"
    assert cinematic.look_for_scene(_scene("At dawn the empire rose")).name == "warm"
    assert cinematic.look_for_scene(_scene("A man walked home")).name == "cinema"


def _duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout
    return float(out.strip())


def _make_clip(tmp_path) -> Path:
    clip = tmp_path / "scene.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0xdddddd:s=640x360:d=2:r=12",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    return clip


@needs_ffmpeg
def test_grade_clip_keeps_the_length_and_changes_the_look(tmp_path):
    clip = _make_clip(tmp_path)
    out = cinematic.grade_clip(clip, _scene("the battle raged", role="hook"), 640, 360, 12, tmp_path)
    assert out != clip and out.exists()
    assert abs(_duration(out) - _duration(clip)) < 0.3          # audio sync must not move
    # the flat light-grey frame is now darker (grade + vignette)
    px = lambda p: subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(p), "-frames:v", "1", "-vf", "scale=1:1",
                                   "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout[0]
    assert px(out) < px(clip)


@needs_ffmpeg
def test_grade_failure_falls_back_to_the_original_clip(tmp_path):
    missing = tmp_path / "nope.mp4"
    assert cinematic.grade_clip(missing, _scene("x"), 640, 360, 12, tmp_path) == missing


@needs_ffmpeg
def test_budget_stops_grading_and_keeps_every_clip(tmp_path):
    clips = [_make_clip(tmp_path)] * 3
    out = cinematic.grade_all(clips, [_scene("x")] * 3, 640, 360, 12, tmp_path, budget_seconds=-1)
    assert out == clips   # nothing graded, nothing lost, same order and count
