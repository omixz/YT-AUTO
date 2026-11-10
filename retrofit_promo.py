"""Daily automatic TikTok for Retrofit (https://retrofit-on12.vercel.app).

Replaces the history cross-posts on the TikTok channel. Each run:
  1. pulls Retrofit's live game-recipe feed and picks the next game it
     hasn't featured yet (rotating hook styles once every game was used),
  2. renders a ~15-20 s vertical video (Pillow frames + edge-tts narration),
  3. hosts it via media_host.py and posts it to TikTok through Buffer.

    python retrofit_promo.py            # make + post today's video
    python retrofit_promo.py --dry-run  # make the video only (output/retrofit_promo/)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import io
import json
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from youtube_automation import fonts

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("retrofit_promo")

SITE = "https://retrofit-on12.vercel.app"
FEED_URL = f"{SITE}/recipes.json"
SCREENSHOT_URL = f"{SITE}/screenshot.png"
HISTORY = Path("config/retrofit_promo_history.json")
OUT = Path("output/retrofit_promo")
VOICE = "en-US-AndrewMultilingualNeural"
W, H = 1080, 1920
BG, FG, MUTED, ACCENT = (18, 18, 18), (236, 236, 236), (170, 170, 170), (255, 140, 50)

HOOKS = [
    "Your PC is too fast for {game}.",
    "{game} is broken on modern PCs. Here's the one-click fix.",
    "Still playing {game} on Windows 11? Watch this.",
]


# ------------------------------------------------------------------ data --

def load_recipes() -> list[dict]:
    r = requests.get(FEED_URL, timeout=30)
    r.raise_for_status()
    recipes = [x for x in r.json().get("recipes", []) if x.get("name")]
    if not recipes:
        raise RuntimeError("Retrofit recipe feed is empty")
    return recipes


def load_history() -> list[dict]:
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return []


def pick(recipes: list[dict], history: list[dict]) -> tuple[dict, str]:
    """Next game not featured yet; once all were used, start a new cycle
    with the next hook style so videos don't repeat word for word."""
    cycle = len(history) // max(len(recipes), 1)
    used = {h["id"] for h in history[cycle * len(recipes):]}
    fresh = [r for r in recipes if r["id"] not in used] or recipes
    recipe = fresh[0]
    return recipe, HOOKS[cycle % len(HOOKS)].format(game=short_name(recipe["name"]))


def short_name(name: str) -> str:
    for cut in (" (", ": The ", " - "):
        if cut in name and len(name) > 28:
            name = name.split(cut)[0]
    return name


def problem_line(r: dict) -> str:
    cap, reason = r.get("fps_cap"), (r.get("cap_reason") or "").strip()
    if cap and reason and "Safe default" not in reason:
        return f"{reason} Retrofit caps it at {cap} FPS automatically."
    return "On modern Windows it can stutter, crash, or show black bars."


def scenes_for(r: dict, hook: str) -> list[dict]:
    game = short_name(r["name"])
    return [
        {"kind": "hook", "title": hook, "say": hook},
        {"kind": "problem", "title": problem_line(r), "say": problem_line(r)},
        {"kind": "app", "title": f"Retrofit fixes {game} in one click.",
         "say": f"Retrofit reads the game, picks the right fix, and you can undo it in one click."},
        {"kind": "cta", "title": "Free · Early access\nretrofit-on12.vercel.app",
         "say": "It's free and in early access. Link in bio."},
    ]


# --------------------------------------------------------------- render --

def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words, cur = para.split(), ""
        for w in words:
            test = f"{cur} {w}".strip()
            if draw.textlength(test, font=font) <= width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def render_frame(scene: dict, path: Path, shot: Image.Image | None) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # warm glow top-left
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    for i in range(60, 0, -1):
        c = tuple(int(BG[k] + (ACCENT[k] - BG[k]) * (0.22 * (1 - i / 60))) for k in range(3))
        gd.ellipse([-i * 14, -i * 12, i * 16, i * 12], fill=c)
    img = Image.blend(img, glow, 0.6)
    d = ImageDraw.Draw(img)

    pad = 90
    tag_font = fonts.load_bold(40)
    size = 100 if scene["kind"] in ("hook", "cta") else 76
    while True:  # shrink until every line (incl. a long URL) fits the width
        title_font = fonts.load_bold(size)
        lines = wrap(d, scene["title"], title_font, W - 2 * pad)
        if all(d.textlength(l, font=title_font) <= W - 2 * pad for l in lines) or size <= 40:
            break
        size -= 4
    line_h = int(title_font.size * 1.18)
    s_img = None
    if scene["kind"] == "app" and shot is not None:
        s_img = shot.copy()
        s_img.thumbnail((W - 2 * pad + 40, 1000))
    block = 76 + 74 + len(lines) * line_h + ((60 + s_img.height) if s_img else 0)
    y = max(220, (H - block) // 2 - 60)   # vertically centred, clear of the footer
    tag = "EARLY ACCESS" if scene["kind"] != "cta" else "RETROFIT"
    tw = d.textlength(tag, font=tag_font)
    d.rounded_rectangle([pad, y, pad + tw + 56, y + 76], radius=38, outline=ACCENT, width=4)
    d.text((pad + 28, y + 14), tag, font=tag_font, fill=ACCENT)
    y += 150
    for i, line in enumerate(lines):
        color = ACCENT if (scene["kind"] == "cta" and i > 0) or (scene["kind"] == "hook" and i == 0) else FG
        d.text((pad, y), line, font=title_font, fill=color)
        y += line_h
    if s_img is not None:
        y += 60
        x = (W - s_img.width) // 2
        d.rounded_rectangle([x - 6, y - 6, x + s_img.width + 6, y + s_img.height + 6], radius=24, fill=(43, 43, 43))
        img.paste(s_img, (x, y))
    foot = fonts.load_bold(44)
    d.text((pad, H - 150), "RETROFIT", font=foot, fill=ACCENT)
    url_font = fonts.load_regular(36)
    url = "retrofit-on12.vercel.app"
    d.text((W - pad - d.textlength(url, font=url_font), H - 144), url, font=url_font, fill=MUTED)
    img.save(path)


VOICES = [VOICE, "en-US-AvaMultilingualNeural", "en-US-GuyNeural"]


async def _tts(text: str, path: Path, voice: str) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice, rate="+8%").save(str(path))


def narrate(text: str, path: Path) -> Path | None:
    """edge-tts occasionally returns 'No audio was received'; retry, then
    fall back to other voices before giving up (silent scene)."""
    import time
    last = None
    for attempt in range(6):
        voice = VOICES[min(attempt // 2, len(VOICES) - 1)]
        try:
            asyncio.run(_tts(text, path, voice))
            if path.exists() and path.stat().st_size > 1000:
                return path
        except Exception as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    log.warning("TTS failed (%s); this scene will be silent", last)
    return None


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def build_video(scenes: list[dict], work: Path) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    try:
        shot = Image.open(io.BytesIO(requests.get(SCREENSHOT_URL, timeout=30).content)).convert("RGB")
    except Exception as exc:
        log.warning("couldn't fetch app screenshot (%s)", exc)
        shot = None
    clips = []
    for i, sc in enumerate(scenes):
        png, mp3, clip = work / f"s{i}.png", work / f"s{i}.mp3", work / f"s{i}.mp4"
        render_frame(sc, png, shot)
        audio = narrate(sc["say"], mp3)
        secs = (duration(audio) + 0.45) if audio else 3.0
        audio_in = ["-i", str(audio)] if audio else ["-f", "lavfi", "-t", f"{secs:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "30", "-t", f"{secs:.2f}", "-i", str(png),
                        *audio_in, "-vf", f"fade=t=in:st=0:d=0.25,fade=t=out:st={secs - 0.25:.2f}:d=0.25,format=yuv420p",
                        "-af", "apad", "-t", f"{secs:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "44100",
                        "-ac", "2", str(clip)], check=True)
        clips.append(clip)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    final = work / "retrofit_promo.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(final)], check=True)
    return final


def caption_for(recipe: dict, hook: str) -> str:
    tag = "".join(ch for ch in short_name(recipe["name"]).lower() if ch.isalnum())
    return (f"{hook} Retrofit is a free Windows app that fixes old PC games in one click (and undoes it in one click). "
            f"Early access, link in bio: retrofit-on12.vercel.app\n\n"
            f"#{tag} #retrogaming #pcgaming #oldgames #pcgamer #gamingtips")


# ----------------------------------------------------------------- main --

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build the video but don't upload or post")
    args = ap.parse_args()

    recipes, history = load_recipes(), load_history()
    recipe, hook = pick(recipes, history)
    log.info("Today's game: %s | hook: %s", recipe["name"], hook)
    video = build_video(scenes_for(recipe, hook), OUT)
    caption = caption_for(recipe, hook)
    (OUT / "caption.txt").write_text(caption)
    log.info("Video: %s (%.1fs)", video, duration(video))
    if args.dry_run:
        return 0

    from youtube_automation import buffer_publisher, media_host
    from youtube_automation.config import PipelineConfig

    config = PipelineConfig.load()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    url = media_host.upload_public(video, f"retrofit-promo-{stamp}.mp4", config)
    post_id = buffer_publisher.publish_tiktok(url, caption, config, title=hook)
    history.append({"id": recipe["id"], "hook": hook, "at": stamp, "buffer_post": post_id})
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=2) + "\n")
    log.info("Posted to TikTok via Buffer: %s", post_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
