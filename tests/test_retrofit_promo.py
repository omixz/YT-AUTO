import retrofit_promo as rp

RECIPES = [{"id": "a", "name": "Game A", "fps_cap": 30, "cap_reason": "Physics break above 30 FPS."},
           {"id": "b", "name": "Star Wars: Knights of the Old Republic (2003 edition)"}]


def test_pick_rotates_games_then_hooks():
    r, hook = rp.pick(RECIPES, [])
    assert r["id"] == "a" and hook == "Your PC is too fast for Game A."
    r, _ = rp.pick(RECIPES, [{"id": "a"}])
    assert r["id"] == "b"
    r, hook = rp.pick(RECIPES, [{"id": "a"}, {"id": "b"}])   # second cycle: new hook style
    assert r["id"] == "a" and hook.startswith("Game A is broken")


def test_problem_and_caption():
    assert "caps it at 30 FPS" in rp.problem_line(RECIPES[0])
    assert "stutter" in rp.problem_line(RECIPES[1])
    cap = rp.caption_for(RECIPES[0], "Hook.")
    assert "#gamea" in cap and "retrofit-on12.vercel.app" in cap
    assert rp.short_name(RECIPES[1]["name"]) == "Star Wars: Knights of the Old Republic"
