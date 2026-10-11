from PIL import Image, ImageDraw

from youtube_automation import thumbnail
from youtube_automation.visuals import VisualAsset


def _asset(tmp_path, name, fill, noisy=False):
    p = tmp_path / name
    im = Image.new("RGB", (1920, 1080), fill)
    if noisy:
        d = ImageDraw.Draw(im)
        for i in range(0, 1920, 40):
            d.rectangle([i, 100 + (i * 7) % 600, i + 30, 900], fill=((i * 3) % 255, (i * 5) % 255, (i * 11) % 255))
    im.save(p, quality=92)
    return VisualAsset(kind="image", path=p)


def test_long_title_is_never_silently_truncated(tmp_path):
    from PIL import ImageFont
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = thumbnail.load_bold(50)
    words = ("THE EXTRAORDINARY STORY OF HOW ONE ENGINEER NOTICED A TINY CRACK IN A BRIDGE "
             "THAT EVERYONE ELSE HAD WALKED PAST FOR YEARS").split()
    lines = thumbnail._wrap_lines(draw, words, font, 500)
    assert sum(len(l) for l in lines) == len(words)          # nothing dropped by the wrapper
    clipped = thumbnail._clip_lines(lines, 3)
    assert len(clipped) == 3 and clipped[-1][-1].endswith("\u2026")  # and any cut is visible


def test_headline_keeps_hook_half_and_drops_filler():
    assert thumbnail._headline("The Ship That Vanished: What Really Happened to the Mary Celeste in 1872") == "The Ship That Vanished"
    h = thumbnail._headline("The Rise and the Fall of the Man Who Sold the Eiffel Tower Twice")
    assert len(h.split()) <= 10 and "Eiffel" in h and "Twice" in h and "On Earth".lower() not in "x"
    assert thumbnail._headline("This Trick Still Fools Every Scientist On Earth") .endswith("On Earth")


def test_war_and_numbers_are_highlight_candidates():
    assert thumbnail._pick_highlight_word("HOW A RADIO CALL STARTED WAR".split()) == "WAR"


def test_thumbnail_stays_under_youtube_2mb_limit(tmp_path):
    out = thumbnail.generate("Why Everything You Know Is Wrong", _asset(tmp_path, "n.jpg", (80, 80, 80), noisy=True),
                             tmp_path, tmp_path / "t.jpg")
    assert out.stat().st_size <= thumbnail.MAX_THUMB_BYTES


def test_best_candidate_frame_beats_a_flat_first_frame(tmp_path):
    flat = _asset(tmp_path, "flat.jpg", (5, 5, 5))              # near-black fade-in frame
    good = _asset(tmp_path, "good.jpg", (60, 90, 140), noisy=True)
    assert thumbnail._score_frame(Image.open(good.path)) > thumbnail._score_frame(Image.open(flat.path))
    out = thumbnail.generate("Test Title", flat, tmp_path, tmp_path / "t.jpg", candidates=[good])
    with Image.open(out) as im:
        px = im.convert("L").resize((32, 18)).getdata()
        assert sum(px) / len(px) > 40                              # not the black frame


def test_bad_candidate_never_breaks_generation(tmp_path):
    bad = VisualAsset(kind="image", path=tmp_path / "missing.jpg")
    out = thumbnail.generate("Test Title", _asset(tmp_path, "ok.jpg", (60, 90, 140)), tmp_path,
                             tmp_path / "t.jpg", candidates=[bad])
    assert out.exists()
