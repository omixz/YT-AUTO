from PIL import Image

from youtube_automation.config import PipelineConfig
from youtube_automation.script_writer import Scene
from youtube_automation import procedural_illustration as pi


def _config():
    config = PipelineConfig.load()
    config.video.format = "longform"
    return config


def test_setting_matched_by_keyword():
    scene = Scene(narration="Snow fell over the frozen village.", visual_keywords=["snow", "village"])
    assert pi._setting_for_scene(scene) == "snow"


def test_setting_falls_back_to_default():
    scene = Scene(narration="Something happened one day.", visual_keywords=[])
    assert pi._setting_for_scene(scene) == "default"


def test_headwear_and_outfit_matched_for_royalty():
    scene = Scene(narration="The king collapsed on the throne.", visual_keywords=["king", "crown"])
    assert pi._match(scene, pi._KEYWORD_TO_HEADWEAR) == "crown"
    assert pi._match(scene, pi._KEYWORD_TO_MOOD) == "shocked"


def test_generate_scene_image_writes_a_real_image_file(tmp_path):
    scene = Scene(narration="The scientist stared at the readings in the lab.", visual_keywords=["scientist", "lab"])
    path = pi.generate_scene_image(scene, 0, _config(), tmp_path)
    assert path.exists()
    with Image.open(path) as img:
        assert img.size == tuple(_config().video.resolution_longform)


def test_generate_all_produces_one_image_per_scene(tmp_path):
    scenes = [
        Scene(narration="A soldier marched through the ruins.", visual_keywords=["soldier", "ruins"]),
        Scene(narration="Rain fell over the quiet farm.", visual_keywords=["farm", "rain"]),
    ]
    paths = pi.generate_all(scenes, _config(), tmp_path)
    assert len(paths) == 2
    assert all(p.exists() for p in paths)


def test_marine_topic_picks_octopus_subject_and_water_setting():
    scene = Scene(narration="The octopus hides in the reef.", visual_keywords=["octopus", "ocean"])
    assert pi._subject_for_scene(scene) == "octopus"
    assert pi._setting_for_scene(scene) == "water"


def test_dominant_subject_covers_scenes_that_dont_name_it():
    scenes = [
        Scene(narration="The octopus has three hearts.", visual_keywords=["octopus"]),
        Scene(narration="Its blood uses a copper-based protein.", visual_keywords=["blood"]),
    ]
    # The whole-video fallback keeps the subject consistent on the second
    # scene, which never says "octopus".
    assert pi._dominant_subject(scenes) == "octopus"


def test_octopus_scene_renders_water_and_subject(tmp_path):
    scene = Scene(narration="Its blood is blue.", visual_keywords=["blood"])
    path = pi.generate_scene_image(scene, 0, _config(), tmp_path, subject_fallback="octopus")
    with Image.open(path) as img:
        # Lower-centre pixel should be water-blue or subject, not white sky.
        w, h = img.size
        assert img.getpixel((int(w * 0.05), int(h * 0.7))) != (255, 255, 255)


def test_scene_clip_is_a_valid_video_of_the_right_length(tmp_path):
    import subprocess
    scene = Scene(narration="The octopus drifts.", visual_keywords=["octopus"])
    clip = pi.generate_scene_clip(scene, 0, _config(), tmp_path, duration=2.0, subject_fallback="octopus")
    assert clip.exists() and clip.suffix == ".mp4"
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(clip)],
        capture_output=True, text=True).stdout.strip()
    assert abs(float(dur) - 2.0) < 0.3


def test_scene_clip_background_actually_pans_not_a_frozen_still(tmp_path):
    # Regression test: a scene with no subject at all used to render as a
    # single frozen frame for its whole duration (the Ken Burns pan/zoom is
    # the fix for that) - assert the background genuinely moves, not just
    # that a video file of the right length exists.
    import subprocess
    from PIL import ImageChops

    scene = Scene(narration="The city stood in silence.", visual_keywords=["city"])
    clip = pi.generate_scene_clip(scene, 3, _config(), tmp_path, duration=3.0)

    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip), "-vf", "select=eq(n\\,0)", "-vframes", "1", str(first)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip), "-vf", "select=eq(n\\,60)", "-vframes", "1", str(last)],
        capture_output=True, check=True,
    )
    with Image.open(first) as a, Image.open(last) as b:
        diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    assert diff.getbbox() is not None, "background frame is identical at t=0 and t=2s - pan/zoom isn't happening"


def test_generate_all_clips_one_per_scene(tmp_path):
    scenes = [
        Scene(narration="A soldier marches.", visual_keywords=["soldier"]),
        Scene(narration="The octopus swims.", visual_keywords=["octopus"]),
    ]
    clips = pi.generate_all_clips(scenes, [1.5, 1.5], _config(), tmp_path)
    assert len(clips) == 2 and all(c.exists() for c in clips)


def test_headwear_drawers_never_leave_a_gap_above_the_head():
    # Regression test: _flat_cap's bounding box once left its flat edge
    # above the head's top edge entirely, so the cap floated free instead
    # of resting on the head (same class of bug _helmet used to have).
    # All headwear drawers should overlap the head circle's top half.
    r = 95.0
    head_cy = 300.0
    head_top = head_cy - r
    for name, drawer in pi._HEADWEAR_DRAWERS.items():
        from PIL import ImageDraw
        img = Image.new("RGB", (600, 600), (255, 255, 255))
        d = ImageDraw.Draw(img)
        drawer(d, 300, head_cy, r)
        # Any non-white pixel at or below the head's top edge means the
        # headwear reaches down to (or overlaps) the head instead of
        # floating entirely above it.
        row = int(head_top)
        pixels = img.load()
        touches_head = any(pixels[x, row] != (255, 255, 255) for x in range(600))
        assert touches_head, f"{name} headwear floats above the head with a visible gap"
