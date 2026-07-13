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
    words_per_scene = max(3, word_count // n_scenes)
    # Distinct text per scene (not just a repeated filler word) so the
    # duplicate-scene check doesn't flag this well-formed fixture itself.
    scenes = [
        Scene(narration=" ".join(f"word{i}_{j}" for j in range(words_per_scene)), visual_keywords=["x"], role="build")
        for i in range(n_scenes)
    ]
    if scenes:
        scenes[0].role = first_role
        scenes[-1].role = last_role
    return Script(
        topic="t", title="How Did the Death of Franz Ferdinand Cause World War I?",
        description="A reasonably descriptive summary of the video content here.",
        tags=["tag1", "tag2", "tag3"], scenes=scenes,
    )


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


def test_check_fails_on_duplicate_scenes():
    script = _script()
    script.scenes[3].narration = script.scenes[1].narration
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("duplicate" in r for r in reasons)


def test_check_fails_on_too_short_scene():
    script = _script()
    script.scenes[2].narration = "Wow."
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("likely truncated" in r for r in reasons)


def test_check_fails_on_refusal_text():
    script = _script()
    script.scenes[2].narration = "I'm sorry, but I cannot provide details about that topic."
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("refused/hedged" in r for r in reasons)


def test_check_fails_on_markdown_artifact():
    script = _script()
    script.scenes[2].narration = "This is **very** important context for the story."
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("markdown" in r for r in reasons)


def test_check_fails_on_placeholder_token():
    script = _script()
    script.scenes[2].narration = "The event happened in [insert year] near the coast."
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("placeholder" in r for r in reasons)


def test_check_fails_on_weak_hook_opener():
    script = _script()
    script.scenes[0].narration = "Today we're looking at a strange mystery from history."
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("throat-clearing" in r for r in reasons)


def test_check_allows_a_strong_hook_opener():
    script = _script()
    script.scenes[0].narration = "A plane vanished mid-radio-call, and no one ever found the wreckage."
    passed, reasons = quality_check.check(script, _config())
    assert passed, reasons


def test_check_fails_on_empty_title():
    script = _script()
    script.title = "   "
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("title is empty" in r for r in reasons)


def test_check_fails_on_thin_description():
    script = _script()
    script.description = "Too short."
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("description is only" in r for r in reasons)


def test_check_fails_on_too_few_tags():
    script = _script()
    script.tags = ["onlyone"]
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("tags" in r for r in reasons)


# --- strong-hook gate (the "10/10, super interesting" bar) ------------------

def test_check_passes_a_causal_hook_title():
    script = _script()
    script.title = "How Did One Assassination Trigger a World War?"
    passed, reasons = quality_check.check(script, _config())
    assert passed, reasons


def test_check_passes_an_immersive_daily_life_title():
    script = _script()
    script.title = "What Was It Really Like to Be a Gladiator in Ancient Rome?"
    passed, reasons = quality_check.check(script, _config())
    assert passed, reasons


def test_check_passes_a_mythology_title():
    script = _script()
    script.title = "The Greek Myth That Terrified an Entire Civilization"
    passed, reasons = quality_check.check(script, _config())
    assert passed, reasons


def test_check_passes_a_hidden_truth_title():
    script = _script()
    script.title = "The Secret the Pharaohs Didn't Want Anyone to Know"
    passed, reasons = quality_check.check(script, _config())
    assert passed, reasons


def test_check_fails_a_vague_listicle_title():
    script = _script()
    script.title = "5 Facts About World War II You Didn't Know"
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("vague listicle" in r for r in reasons)


def test_check_fails_a_bare_topic_label_title():
    script = _script()
    script.title = "Ancient Rome: A Documentary"
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("vague listicle" in r for r in reasons)


def test_check_fails_bare_mythology_label_despite_containing_myth_substring():
    # Regression test: "myth" is a substring of "Mythology", so a naive
    # substring check let this exact bare-label title through.
    script = _script()
    script.title = "Greek Mythology Explained"
    passed, reasons = quality_check.check(script, _config())
    assert not passed
    assert any("vague listicle" in r for r in reasons)


def test_check_passes_a_title_using_the_standalone_word_myth():
    script = _script()
    script.title = "The Myth That Terrified an Ancient Civilization"
    passed, reasons = quality_check.check(script, _config())
    assert passed, reasons


def test_strong_hook_gate_can_be_disabled():
    config = _config()
    config.quality.require_strong_hook = False
    script = _script()
    script.title = "5 Facts About World War II You Didn't Know"
    passed, reasons = quality_check.check(script, config)
    assert passed, reasons


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
