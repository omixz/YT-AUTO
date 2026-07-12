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
