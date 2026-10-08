from youtube_automation.script_writer import _repair_roles, _draft_text

W = " ".join(["word"] * 30)


def _d(roles, last_words=30):
    sc = [{"role": r, "narration": W, "visual_keywords": []} for r in roles]
    sc[-1]["narration"] = " ".join(["w"] * last_words)
    return {"scenes": sc}


def test_mislabeled_last_scene_becomes_insight():
    d = _repair_roles(_d(["hook", "build", "build"]))
    assert d["scenes"][-1]["role"] == "insight"


def test_mislabeled_first_scene_becomes_hook():
    d = _repair_roles(_d(["build", "build", "insight"]))
    assert d["scenes"][0]["role"] == "hook"


def test_tiny_last_scene_is_left_for_the_quality_gate():
    d = _repair_roles(_d(["hook", "build", "build"], last_words=3))
    assert d["scenes"][-1]["role"] == "build"


def test_correct_roles_untouched_and_empty_ok():
    d = _repair_roles(_d(["hook", "build", "insight"]))
    assert [s["role"] for s in d["scenes"]] == ["hook", "build", "insight"]
    assert _repair_roles({"scenes": []}) == {"scenes": []}


def test_draft_text_joins_scene_narration():
    assert _draft_text({"scenes": [{"narration": " a "}, {"narration": "b"}]}) == "a\n\nb"
