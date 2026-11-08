"""Characters match the story: named cast honoured, consistent skin/gender, companions on screen, era-right props."""
import random

import pytest

from youtube_automation.script_writer import SCRIPT_SCHEMA, Scene
from youtube_automation.toon import casting, direction
from youtube_automation.toon.character import PROPS, SKIN_TONES
from youtube_automation.toon.sets import build_set

CHARS = [{"name": "Gavrilo", "gender": "male", "skin": "light", "age": "young", "kind": "civilian"},
         {"name": "Sophie", "gender": "female", "skin": "light", "age": "adult", "kind": "royal"},
         {"name": "Ade", "gender": "male", "skin": "dark", "age": "old", "kind": "soldier"}]


def test_named_cast_is_honoured_in_every_scene():
    scenes = [Scene("In 1914 Gavrilo waited with a pistol.", ["x"], on_screen=["Gavrilo"], prop="pistol"),
              Scene("Sophie and Gavrilo met.", ["x"], on_screen=["sophie", "Gavrilo"]),
              Scene("Ade marched.", ["x"], on_screen=["Ade"])]
    d = direction.direct(scenes, [3.0] * 3, "T", characters=CHARS)
    assert not d[0].hero.female and d[0].hero.skin == SKIN_TONES[0] and d[0].hero.prop == "pistol"
    assert d[1].hero.female and d[1].hero.headwear == "crown"
    assert d[2].hero.skin == SKIN_TONES[4] and d[2].hero.hair == (214, 214, 218) and d[2].hero.style == "uniform"
    if d[1].shot != "close":
        assert len(d[1].companions) == 1 and not d[1].companions[0].female


def test_same_person_keeps_the_same_look_across_scenes():
    scenes = [Scene(f"Scene {i} in 1914.", ["x"], on_screen=["Sophie"]) for i in range(4)]
    d = direction.direct(scenes, [3.0] * 4, "T", characters=CHARS)
    assert len({(x.hero.skin, x.hero.female, x.hero.hair) for x in d}) == 1


def test_fallback_cast_uses_one_regional_palette_and_pronouns():
    text = "In 1945 a Japanese nurse in Tokyo kept a diary. She wrote every night. Her sister hid it. She survived."
    scenes = [Scene(s + ".", ["x"]) for s in text.split(". ")]
    d = direction.direct(scenes, [3.0] * len(scenes), "The Tokyo Diary")
    tones = {x.hero.skin for x in d} | {c.skin for x in d for c in x.companions}
    assert tones <= {SKIN_TONES[0], SKIN_TONES[1]}
    assert all(x.hero.female for x in d if casting.scene_gender(scenes[x.index].narration) is True)
    assert d[1].hero.female   # "She wrote every night."


def test_group_scenes_get_companions():
    scenes = [Scene("The two brothers argued all night in 1890.", ["x"], action="talk")] * 6
    d = direction.direct(scenes, [3.0] * 6, "T")
    assert any(len(x.companions) >= 1 for x in d)
    assert all(not x.companions for x in d if x.shot == "close")


@pytest.mark.parametrize("era,said,expect", [("ancient", "rifle", None), ("ww1", "rifle", "rifle"), ("ww2", "sword", None),
                                               ("medieval", "sword", "sword"), ("modern", "letter", "letter")])
def test_props_respect_the_era(era, said, expect):
    assert casting.prop_for("nothing relevant here", era, said) == expect


def test_props_from_narration():
    assert casting.prop_for("He read the telegram twice.", "ww1") == "letter"
    assert casting.prop_for("The general unrolled a map.", "ww2") == "map"
    assert casting.prop_for("A musket shot rang out.", "ancient") is None


def test_schema_props_are_all_drawable():
    enum = SCRIPT_SCHEMA["properties"]["scenes"]["items"]["properties"]["prop"]["enum"]
    assert set(enum) - {""} <= set(PROPS)
    assert "characters" in SCRIPT_SCHEMA["properties"]


@pytest.mark.parametrize("setting", direction.VALID_SETTINGS)
def test_every_setting_builds(setting):
    for w, h in ((480, 270), (270, 480)):
        for tod in ("day", "dusk", "night"):
            s = build_set(setting, tod, w, h, random.Random(1))
            assert s.layers and 0 < s.ground_y < h
