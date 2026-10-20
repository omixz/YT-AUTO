import random

import pytest

from youtube_automation import script_writer as sw
from youtube_automation.script_writer import Scene
from youtube_automation.toon import direction
from youtube_automation.toon.sets import build_set

NEW = ["battlefield", "warroom", "shipdeck", "island"]


def test_model_direction_wins_and_is_validated():
    scenes = [Scene("He walked in.", ["x"], "build", setting="warroom", action="talk", mood="serious", time_of_day="night"),
              Scene("Nonsense values.", ["x"], "build", setting="moonbase", action="teleport", mood="angry", time_of_day="noon")]
    d = direction.direct(scenes, [4.0, 4.0])
    assert (d[0].setting, d[0].mood, d[0].tod) == ("warroom", "serious", "night")
    assert d[1].setting in direction.VALID_SETTINGS and d[1].action in direction.VALID_ACTIONS   # bad values fall back safely


def test_keyword_fallback_never_invents_fights_or_crowds():
    scenes = [Scene("The soldiers fought and clashed as the army and the crowd gathered.", ["battle", "soldiers"], "build") for _ in range(4)]
    assert {d.action for d in direction.direct(scenes, [4.0] * 4)} <= {"talk", "walk"}


def test_no_two_busy_scenes_in_a_row():
    scenes = [Scene("a", ["x"], "build", action="fight"), Scene("b", ["x"], "build", action="crowd"), Scene("c", ["x"], "build", action="fight")]
    acts = [d.action for d in direction.direct(scenes, [4.0] * 3)]
    assert acts == ["fight", "talk", "fight"]


def test_fallback_hints_pick_matching_new_sets():
    d = direction.direct([Scene("The general studied the map in headquarters.", ["x"]), Scene("Passengers aboard the cruise ship slept.", ["x"])], [4.0, 4.0])
    assert [x.setting for x in d] == ["warroom", "shipdeck"]


@pytest.mark.parametrize("setting", NEW)
def test_new_sets_build(setting):
    s = build_set(setting, "day", 320, 180, random.Random(1))
    assert len(s.layers) >= 3 and s.tile_w > 0


def test_schema_lists_settings_and_scene_defaults():
    props = sw.SCRIPT_SCHEMA["properties"]["scenes"]["items"]["properties"]
    assert set(NEW) <= set(props["setting"]["enum"]) and "fight" in props["action"]["enum"]
    sc = Scene("n", ["k"])
    assert sc.setting == "" and sc.action == "" and sc.role == "build"
