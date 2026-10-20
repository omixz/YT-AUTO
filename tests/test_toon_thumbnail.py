from youtube_automation.script_writer import Scene
from youtube_automation.toon import thumbnail as T


def test_pick_text_prefers_short_honest_model_text():
    assert T.pick_text("Some Long Title Here", "they vanished?") == "THEY VANISHED?"
    assert T.pick_text("Title", "This Proves The Whole Cover Up Was Real") != "THIS PROVES THE WHOLE COVER UP WAS REAL"   # too long + overclaim -> ignored


def test_pick_text_cuts_a_punchy_clause_from_the_title():
    assert T.pick_text("The General Who Saved France: Lanrezac's Last Order") == "LANREZAC'S LAST ORDER"
    t = T.pick_text("The Disappearance of Three Keepers That Terrified a Nation")
    assert 1 <= len(t.split()) <= 3 and "DISAPPEARANCE" in t


def test_render_makes_a_valid_small_jpeg(tmp_path):
    scenes = [Scene("In 1912 keepers vanished.", ["x"], "hook", setting="island", mood="shocked")]
    out = T.render(scenes, [4.0], "The 1912 Lighthouse Mystery", tmp_path / "t.jpg", "THEY VANISHED?")
    data = out.read_bytes()
    assert data[:2] == b"\xff\xd8" and 20_000 < len(data) < 1_900_000
