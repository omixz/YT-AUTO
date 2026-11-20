"""Daily AI "Roblox story" Short: AI-written first-person Roblox drama, narrated, captioned, over obby gameplay.

Runs alongside the history pipeline but shares nothing with it except the uploader and the Gemini helper:
its own config (config/roblox_stories.yaml), history (config/roblox_stories_history.json) and workflow.

    python roblox_stories.py             # write, render and upload today's story
    python roblox_stories.py --dry-run   # write and render only (output/roblox_stories/)
    python roblox_stories.py --auth      # one-time: log in to the stories channel and mint its token
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import logging
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import yaml

from youtube_automation.stories.captions import Word, build_ass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("roblox_stories")

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "roblox_stories.yaml"
HISTORY = ROOT / "config" / "roblox_stories_history.json"
OUT = ROOT / "output" / "roblox_stories"
FONTS = ROOT / "assets" / "fonts"
W, H, FPS = 1080, 1920, 30

GAMES = ["Brookhaven", "Adopt Me", "Tower of Hell", "Blox Fruits", "Murder Mystery 2", "Grow a Garden",
         "Natural Disaster Survival", "Dress to Impress", "Bee Swarm Simulator", "an obby"]

STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "YouTube Shorts title, 35-70 chars, curiosity gap, no clickbait lies, no emojis."},
        "hook_text": {"type": "string", "description": "On-screen opening card, 3-8 words, the most intriguing line (e.g. 'My best friend scammed me...')."},
        "story": {"type": "string", "description": "The narration, first person, plain text, no headings or stage directions."},
        "game": {"type": "string", "description": "Which game the story is set in."},
        "description": {"type": "string", "description": "2-3 sentence YouTube description ending with a question for the comments."},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "hook_text", "story", "game", "description", "tags"],
}


def load_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def load_history() -> list:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


# ---------------------------------------------------------------- story --

def story_prompt(cfg: dict, history: list, game: str) -> str:
    recent = "\n".join(f"- {h['title']}" for h in history[-30:]) or "- (none yet)"
    return f"""Write ONE original, fictional first-person story for a vertical YouTube Short in the
"Roblox story" format: a narrator tells a dramatic thing that happened to them while playing {game} on Roblox,
read aloud by an AI voice over parkour gameplay.

LENGTH: {cfg.get('min_words', 110)}-{cfg.get('max_words', 170)} words of narration (about 45-60 seconds).

WHAT MAKES THESE GO VIRAL - follow all of it:
- Sentence 1 is the hook: the most dramatic moment or betrayal, mid-action, under 15 words.
  e.g. "My best friend traded away my neon unicorn while I was AFK." Never start with "So", "Hey guys", "Once".
- Everyday kid/teen stakes that feel huge: a scam, a betrayal by a friend, a sibling, a rich player, a
  secret base, a rare item, an admin, a lie that spirals. Concrete in-game details (items, places, mechanics).
- Short spoken sentences. Every 2-3 sentences, a new twist or escalation. No filler, no morals, no recap.
- The ending is a satisfying twist or comeback in the last 1-2 sentences, then ONE short question to the
  viewer that invites comments (e.g. "Would you have forgiven her?").
- It must be clearly a story, never presented as news or as something a real, named person did.

SAFETY (the audience includes young teens - non-negotiable): no romance or dating, no swearing, no violence
beyond in-game cartoon stuff, no real usernames, no real people, no hate, no self-harm, no scary adult
themes, no encouraging scams or hacking, no off-platform contact. Nothing that breaks Roblox's or YouTube's rules.

Do not repeat or lightly rework any of these recent stories:
{recent}"""


def write_story(cfg: dict, history: list) -> dict:
    from youtube_automation.config import PipelineConfig
    from youtube_automation.script_writer import _call_gemini

    config = PipelineConfig.load()
    recent_games = [h.get("game") for h in history[-4:]]
    game = random.choice([g for g in GAMES if g not in recent_games] or GAMES)
    lo, hi = int(cfg.get("min_words", 110)), int(cfg.get("max_words", 170))
    last_err = ""
    for attempt in range(3):
        data = _call_gemini(story_prompt(cfg, history, game) + last_err, "emit_story", STORY_SCHEMA, config, 4096)
        n = len(data.get("story", "").split())
        if lo * 0.85 <= n <= hi * 1.2 and data.get("title"):
            data["story"] = " ".join(data["story"].split())
            return data
        last_err = f"\n\nYour last attempt was {n} words. It MUST be {lo}-{hi} words."
        log.warning("story attempt %d: %d words, retrying", attempt + 1, n)
    raise RuntimeError("Gemini did not produce a story of usable length")


# ---------------------------------------------------------------- voice --

def _ssl_ctx():
    """edge-tts pins certifi; honour a custom CA bundle (corporate/agent proxies) when one is configured."""
    import ssl
    bundle = os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=bundle) if bundle and Path(bundle).exists() else None


async def _speak(text: str, voice: str, rate: str, mp3: Path) -> List[Word]:
    import edge_tts
    import edge_tts.communicate as ec
    ctx = _ssl_ctx()
    if ctx is not None:
        ec._SSL_CTX = ctx
    words: List[Word] = []
    with open(mp3, "wb") as f:
        async for ch in edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary").stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append((start, start + ch["duration"] / 1e7, ch["text"]))
    return words


def narrate(text: str, mp3: Path, cfg: dict) -> List[Word]:
    """edge-tts sometimes returns no audio; retry, then fall back to other voices."""
    import time
    voices = [cfg.get("voice", "en-US-AnaNeural"), "en-US-AvaMultilingualNeural", "en-US-AndrewMultilingualNeural"]
    last: Exception | None = None
    for attempt in range(6):
        try:
            words = asyncio.run(_speak(text, voices[min(attempt // 2, 2)], cfg.get("voice_rate", "+12%"), mp3))
            if mp3.exists() and mp3.stat().st_size > 5000 and words:
                return _attach_punctuation(words, text)
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"TTS failed: {last}")


def _attach_punctuation(words: List[Word], text: str) -> List[Word]:
    """Word boundaries come without punctuation; copy it back from the script so captions break on sentences."""
    tokens = text.split()
    out, j = [], 0
    for start, end, w in words:
        tok = w
        for k in range(j, min(j + 4, len(tokens))):
            if "".join(c for c in tokens[k] if c.isalnum()).lower() == "".join(c for c in w if c.isalnum()).lower():
                tok, j = tokens[k], k + 1
                break
        out.append((start, end, tok))
    return out


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# ----------------------------------------------------------- background --

def gameplay_clips(cfg: dict) -> List[Path]:
    """Your own recorded gameplay: local files, plus any URLs in STORIES_GAMEPLAY_URLS (downloaded once)."""
    folder = ROOT / cfg.get("gameplay_dir", "assets/gameplay")
    clips = sorted(folder.glob("*.mp4")) if folder.exists() else []
    urls = [u.strip() for u in os.getenv("STORIES_GAMEPLAY_URLS", "").split(",") if u.strip()]
    if urls:
        import requests
        cache = OUT / "gameplay"
        cache.mkdir(parents=True, exist_ok=True)
        for i, url in enumerate(urls):
            dest = cache / f"clip_{i}.mp4"
            if not dest.exists():
                try:
                    with requests.get(url, timeout=120, stream=True) as r:
                        r.raise_for_status()
                        with open(dest, "wb") as f:
                            for chunk in r.iter_content(1 << 20):
                                f.write(chunk)
                except Exception as exc:  # noqa: BLE001
                    log.warning("couldn't download gameplay clip %d (%s)", i, exc)
                    continue
            clips.append(dest)
    return [c for c in clips if c.exists() and c.stat().st_size > 100_000]


def render(story: dict, mp3: Path, words: List[Word], cfg: dict, out: Path, seed: int) -> Tuple[Path, str]:
    """Returns (video, background_kind)."""
    secs = duration(mp3) + 0.7
    ass = out.parent / "captions.ass"
    ass.write_text(build_ass(words, story.get("hook_text", ""), title_secs=min(2.8, secs)), encoding="utf-8")
    subs = f"subtitles={ass.as_posix()}:fontsdir={FONTS.as_posix()}"
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", "-t", f"{secs:.2f}"]
    clips = gameplay_clips(cfg)
    if clips:
        clip = random.Random(seed).choice(clips)
        start = random.Random(seed + 1).uniform(0, max(0.0, duration(clip) - secs - 1))
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,{subs}"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(clip),
                        "-i", str(mp3), "-map", "0:v", "-map", "1:a", "-vf", vf, "-af", "apad", *enc, str(out)], check=True)
        return out, "gameplay"

    from youtube_automation.stories import obby
    proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", str(mp3), "-map", "0:v", "-map", "1:a", "-vf", subs,
                             "-af", "apad", *enc, str(out)], stdin=subprocess.PIPE)
    try:
        for frame in obby.frames(secs, W, H, FPS, seed=seed):
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed rendering the story video")
    return out, "procedural"


# ---------------------------------------------------------------- upload --

def token_path(cfg: dict) -> Path:
    if cfg.get("channel", "separate") == "main":
        return Path(os.getenv("YOUTUBE_TOKEN_FILE", "token.json"))
    return Path(os.getenv("STORIES_TOKEN_FILE", "stories_token.json"))


def upload_config(cfg: dict):
    from youtube_automation.config import PipelineConfig
    base = PipelineConfig.load()
    return dataclasses.replace(
        base,
        secrets=dataclasses.replace(base.secrets, youtube_token_file=str(token_path(cfg))),
        upload=dataclasses.replace(base.upload, privacy_status=cfg.get("privacy_status", "public"),
                                   category_id=str(cfg.get("category_id", "20")),
                                   made_for_kids=bool(cfg.get("made_for_kids", False)), default_tags=[]),
    )


def description_for(story: dict) -> str:
    return (f"{story['description'].strip()}\n\nThis is a fictional story narrated with an AI voice.\n\n"
            "#roblox #robloxstory #storytime #shorts")


def auth() -> int:
    from youtube_automation.youtube_auth import get_credentials
    cfg = load_cfg()
    path = token_path(cfg)
    if path.exists():
        path.unlink()
    get_credentials(upload_config(cfg))   # opens the browser: pick the STORIES channel when Google asks
    print(f"\nSaved {path}. Add it to GitHub as the YOUTUBE_STORIES_TOKEN_B64 secret:\n"
          f"  base64 -w0 {path}    (macOS: base64 -i {path})\n")
    return 0


def _summary(text: str) -> None:
    log.info(text)
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


# ------------------------------------------------------------------- main --

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write and render, don't upload")
    ap.add_argument("--auth", action="store_true", help="one-time login for the stories channel")
    args = ap.parse_args()
    if args.auth:
        return auth()

    cfg = load_cfg()
    if not cfg.get("enabled", True):
        log.info("roblox stories disabled in config/roblox_stories.yaml")
        return 0
    history = load_history()
    OUT.mkdir(parents=True, exist_ok=True)

    story = write_story(cfg, history)
    log.info("Story: %s (%s, %d words)", story["title"], story["game"], len(story["story"].split()))
    mp3 = OUT / "voice.mp3"
    words = narrate(story["story"], mp3, cfg)
    seed = int(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d"))
    video, bg = render(story, mp3, words, cfg, OUT / "roblox_story.mp4", seed)
    (OUT / "story.json").write_text(json.dumps({**story, "background": bg}, indent=2), encoding="utf-8")
    log.info("Video: %s (%.1fs, %s background)", video, duration(video), bg)
    if bg == "procedural":
        log.info("Tip: add your own recorded gameplay to assets/gameplay/ for a more authentic look.")
    if args.dry_run:
        return 0

    if not token_path(cfg).exists():
        _summary(f"**Roblox story built but NOT posted**: no token for the `{cfg.get('channel', 'separate')}` channel. "
                 "Run `python roblox_stories.py --auth` once and add the YOUTUBE_STORIES_TOKEN_B64 secret "
                 "(or set `channel: main` in config/roblox_stories.yaml). The video is in this run's artifacts.")
        return 0

    from youtube_automation.youtube_uploader import upload_video
    video_id = upload_video(video, story["title"], description_for(story),
                            list(dict.fromkeys(cfg.get("tags", []) + story.get("tags", [])))[:15], upload_config(cfg))
    history.append({"date": dt.date.today().isoformat(), "title": story["title"], "game": story["game"],
                    "video_id": video_id, "channel": cfg.get("channel", "separate"), "background": bg})
    HISTORY.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    _summary(f"**Posted Roblox story**: [{story['title']}](https://youtu.be/{video_id}) ({bg} background)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
