from youtube_automation.quality_check import drop_defective_scenes
from youtube_automation.script_writer import Scene, Script


def _script(n=40, **over):
    scenes = [Scene(f"Unique narration for scene number {i} with enough words to count.", ["x"], "build") for i in range(n)]
    scenes[0].role, scenes[-1].role = "hook", "insight"
    for i, text in over.items():
        scenes[int(i[1:])].narration = text
    return Script(topic="t", title="t", description="d", tags=[], scenes=scenes)


def test_one_refused_scene_is_dropped_and_roles_hold():
    s = _script(s5="I cannot fulfill this request as it involves graphic content.")
    assert drop_defective_scenes(s) == 1 and len(s.scenes) == 39
    assert s.scenes[0].role == "hook" and s.scenes[-1].role == "insight"


def test_duplicates_and_fragments_go_but_first_scene_removal_relabels_hook():
    s = _script(s0="Hi.", s7="Unique narration for scene number 3 with enough words to count.")
    assert drop_defective_scenes(s) == 2 and s.scenes[0].role == "hook"


def test_too_many_defects_are_left_for_the_gate_to_judge():
    s = _script(n=40, s1="I cannot do that.", s2="I cannot do that either.", s3="I'm sorry, I can't help with that.")
    before = len(s.scenes)
    assert drop_defective_scenes(s) == 0 and len(s.scenes) == before
