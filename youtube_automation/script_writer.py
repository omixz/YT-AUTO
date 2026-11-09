"""Generates a scene-by-scene video script for a topic, using Gemini function-
calling for guaranteed-structured output (no fragile JSON-in-prose parsing).

Uses the raw REST API via `requests` (already a project dependency) rather
than adding the google-genai SDK - the request/response shapes are simple
enough that a thin wrapper here is less to maintain than a full SDK.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Tuple

import requests

from .config import PipelineConfig

logger = logging.getLogger(__name__)

# Pinned to gemini-3.5-flash-lite - a specific, stable, GA model id, NOT a
# rolling "-latest" alias (which silently hot-swaps to whatever release is
# current) and NOT gemini-2.5-flash (which turned out to already be
# deprecated: "no longer available to new users", a live 404 on a real
# scheduled run). Pinning to an explicit stable id means this can't get
# silently broken again by a future release swap; bump deliberately.
#
# Switched from gemini-3.5-flash to the -lite variant after the free-tier
# gemini-3.5-flash quota (confirmed via a real 429 response body: 20
# requests/day, quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier)
# repeatedly blocked real runs - each pipeline run needs several Gemini
# calls (topic brainstorm, up to 4 script-generation attempts), so 20/day
# barely covers one run, let alone survives any manual testing on top of
# the scheduled run. Free-tier quotas are allocated per-model, and every
# source checked (Google's own docs plus third-party API references)
# consistently describes Flash-Lite tiers as the higher-throughput,
# higher-RPD option specifically meant for exactly this kind of high-
# volume, low-complexity structured-output workload - confirmed as a real,
# valid model id supporting function calling, structured JSON output and
# Search grounding (google_search tool), all of which this file already
# depends on, so no other code here needs to change for the switch itself.
# If a future run still hits a 429 with "PerDay" in its quotaId even on
# this model, _daily_quota_exhausted_message() below will say so plainly
# rather than needing another guess-and-check cycle to find out.
MODEL = "gemini-3.5-flash-lite"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "YouTube title, under 100 chars, hook-forward. Makes one specific, curiosity-gap promise (not a vague topic label) - the hook scene's opening line must deliver on exactly this promise, since a title/thumbnail that overpromises what the video actually opens with kills retention and the algorithm's willingness to keep distributing it."},
        "description": {"type": "string", "description": "YouTube description, 2-4 sentences plus hashtags."},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "8-15 relevant search tags."},
        "title_options": {"type": "array", "items": {"type": "string"}, "description": "3 alternative titles (different angles), 35-65 chars each."},
        "thumbnail_text": {"type": "string", "description": "2-4 ALL-CAPS-friendly words for the thumbnail (e.g. \"THEY VANISHED?\", \"NO SURVIVORS\", \"THE LAST ORDER\"). Must add curiosity the title does not already give - never repeat the title, never state an unproven claim as fact."},
        "scenes": {
            "type": "array",
            "description": "Ordered scenes that make up the full narration.",
            "items": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["hook", "build", "insight"],
                        "description": (
                            "hook: exactly the first scene. Opens by delivering on the title's exact "
                            "promise in its very first sentence - no scene-setting, no 'today we're "
                            "looking at...' throat-clearing, since viewers decide whether to keep "
                            "watching within seconds and a slow open loses them before the rest of "
                            "the script gets a chance. Vary the opening device by topic - a blunt "
                            "shocking statement, a direct 'Did you know...' curiosity trigger, or a "
                            "rhetorical question that opens a loop - whichever creates the sharpest "
                            "curiosity gap for this specific topic. This scene's visual_keywords double "
                            "as the video's thumbnail (its rendered frame is used as-is), so they must "
                            "name ONE single, concrete, visually striking moment or image from the "
                            "title's promise (a specific object, action, or expression - something that "
                            "reads instantly at thumbnail size in a crowded feed), never an abstract or "
                            "establishing-shot description. "
                            "build: 3+ middle scenes that develop connected facts into a mini-story "
                            "(use transitions like 'but here's the twist' / 'and that's not even "
                            "the strangest part' - don't just list isolated trivia). The SECOND scene "
                            "specifically must land a fresh escalation or twist of its own (not just "
                            "restate/explain the hook) - this is the point, roughly 20-30 seconds in, "
                            "where most viewers who clicked decide whether to keep watching, and a "
                            "scene that merely elaborates on what the hook already said is exactly "
                            "what makes them leave. "
                            "insight: exactly the last scene - a genuine 'why this matters' "
                            "synthesis, not just another fact."
                        ),
                    },
                    "narration": {
                        "type": "string",
                        "description": "What the voiceover says for this scene, one or two sentences.",
                    },
                    "visual_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-4 stock-footage search terms depicting this scene.",
                    },
                    "on_screen_text": {
                        "type": "string",
                        "description": "Short on-screen caption/emphasis text. Empty string if none.",
                    },
                    "setting": {"type": "string", "enum": ['default', 'city', 'courtroom', 'desert', 'dungeon', 'forest', 'government', 'harbor', 'indoor', 'mountain', 'mythic', 'palace', 'ruins', 'snow', 'water', 'ancient', 'battlefield', 'warroom', 'shipdeck', 'island',
                                                            'village', 'jungle', 'camp', 'street', 'library', 'church', 'tavern'],
                                "description": "The place this scene physically happens - pick the closest match to the narration."},
                    "action": {"type": "string", "enum": ['talk', 'walk', 'fight', 'crowd', 'shock'],
                               "description": "What the on-screen character does. talk = stands/thinks/explains (use for most scenes); walk = travelling; fight = ONLY actual hand-to-hand combat; crowd = ONLY a large group is the point; shock = a startled reveal."},
                    "mood": {"type": "string", "enum": ["neutral", "serious", "shocked"]},
                    "time_of_day": {"type": "string", "enum": ["day", "dusk", "night"]},
                    "on_screen": {"type": "array", "items": {"type": "string"},
                                  "description": "Names (from `characters`) of the 1-3 people visible in this scene, the main one first."},
                    "prop": {"type": "string", "enum": ["none", "rifle", "pistol", "sword", "spear", "axe", "shield", "book", "letter", "map",
                                                       "scroll", "torch", "lantern", "telescope", "bag", "compass"],
                             "description": "What the main person holds, only if the narration involves it and it fits the era; else none."},
                },
                "required": ["role", "narration", "visual_keywords"],
            },
        },
        "characters": {
            "type": "array",
            "description": "The real people in this story (2-5), so the cartoon shows the right person in every scene.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short name used in scenes' on_screen, e.g. \"Gavrilo\" or \"the guard\"."},
                    "gender": {"type": "string", "enum": ["male", "female"]},
                    "skin": {"type": "string", "enum": ["light", "olive", "tan", "brown", "dark"],
                             "description": "Historically accurate for this real person."},
                    "age": {"type": "string", "enum": ["young", "adult", "old"]},
                    "kind": {"type": "string", "enum": ["civilian", "soldier", "officer", "royal", "scholar", "priest", "worker",
                                                        "sailor", "criminal", "detective"]},
                },
                "required": ["name", "gender", "skin"],
            },
        },
    },
    "required": ["title", "description", "tags", "scenes"],
}

EMIT_SCRIPT = "emit_script"
EMIT_TOPICS = "emit_topics"

# Real production incident this guards against: a script came back at ~45%
# of its requested length (a 20-minute/1200s target produced only a ~9-
# minute video), and shipped anyway - the prompt only asks for "roughly"
# the target words/scenes, a soft ask the model doesn't always honor,
# especially for a topic whose natural story arc feels "finished" well
# before the requested length. Used by generate_script() below as the
# trigger for retrying with a reinforced prompt - deliberately kept
# aggressive/high, since the only cost of retrying "too eagerly" is one
# extra cheap Gemini call, not a blocked publish. See
# MIN_PUBLISH_DURATION_FRACTION for the separate, more lenient threshold
# that actually decides whether a video is good enough to ship.
#
# Raised from 0.7 to 0.85 after a second incident showed 0.7 wasn't enough
# headroom on its own: the channel went quiet for 4 real days (last public
# video Sep 17; every attempt Sep 14/15/20 correctly got caught and kept
# private, never crashing, just never shipping) because a script could
# clear the OLD 0.7 bar on word count while still rendering short once
# actually spoken - see _script_length_params()'s wpm comment for why the
# word-count estimate itself was still too generous even post-retry.
MIN_TARGET_LENGTH_FRACTION = 0.85

# Separate from MIN_TARGET_LENGTH_FRACTION above on purpose: that constant
# exists to keep PUSHING generate_script() to try harder (cheap to be
# aggressive about, since retrying just costs one more API call), but this
# one is the actual "is this video good enough to publish" bar - and being
# too aggressive here has a real cost, since it means a genuinely solid,
# complete, coherent video gets hidden as private just for landing at 16-17
# minutes instead of a full 20. Used by quality_check.py for both the
# script-level word-count sanity check and the final real-duration check,
# so a script doesn't get blocked by one threshold only to have cleared the
# other. Real incident: a script that only cleared the retry loop at 2589
# words (against a 2805-word/0.85 bar) would, at the observed real ~154-165
# wpm pace, still render to a genuinely watchable ~16 minutes - comfortably
# worth publishing, not worth hiding, hence 0.75 (15 min for a 20-min
# target) here rather than reusing 0.85.
MIN_PUBLISH_DURATION_FRACTION = 0.75

# Transient 429/503 "overloaded/rate-limited" responses, and read timeouts
# under load, are common and worth retrying rather than failing a whole
# scheduled run over it (this has actually happened: a 503 and, separately,
# a bare ReadTimeout - the latter isn't an HTTP status at all, so it needs
# its own except clause below rather than just growing this set).
#
# A real scheduled run hit a Gemini 503 "high demand" spike that outlasted
# the old 4-retry/~15s-total budget (1+2+4+8s) and killed the whole day's
# video before any content was generated. Google's own guidance for these is
# "usually temporary" on the order of a minute or so, not 15 seconds, so the
# budget is widened to ~2 minutes of total backoff (capped per-sleep so it
# doesn't runaway) - a scheduled job losing an extra minute to retries is
# free; losing the whole day's video to a spike that would've cleared 30
# seconds later is not.
_RETRY_STATUSES = {429, 503}
# Bumped from 7 retries/60s cap after three separate scheduled runs (Sep 15,
# 16, 18) all failed on the same Gemini 503 "high demand" error, at similar
# times of day - suggesting genuine sustained congestion at that slot, not
# an isolated blip the old budget (~123s total wait across 7 retries) could
# reliably ride out. 10 retries with a 120s cap gives ~8 minutes of total
# wait before giving up, which is a small addition against a full pipeline
# run's 15-25 minute runtime, but meaningfully more likely to survive a
# sustained outage rather than exhausting retries partway through it.
_MAX_RETRIES = 10
_MAX_BACKOFF_SECONDS = 120


@dataclass
class Scene:
    narration: str
    visual_keywords: List[str]
    role: str = "build"
    on_screen_text: str = ""
    # Per-scene direction chosen by the script model (all optional; the toon renderer falls back to keywords)
    setting: str = ""       # where the scene physically takes place
    action: str = ""        # what the hero is doing
    mood: str = ""          # neutral | serious | shocked
    time_of_day: str = ""   # day | dusk | night
    on_screen: List[str] = field(default_factory=list)   # names from Script.characters visible in this scene (main first)
    prop: str = ""          # what the main person holds (validated against the era by toon/casting.py)
    kind: str = ""          # "" for story scenes; "cta_break" for the inserted like-and-subscribe beat (never part of the story)


@dataclass
class Script:
    topic: str
    title: str
    description: str
    tags: List[str]
    scenes: List[Scene] = field(default_factory=list)
    title_options: List[str] = field(default_factory=list)   # alternative titles from the same call; quality_check.pick_best_title chooses
    characters: List[dict] = field(default_factory=list)   # real people: name/gender/skin/age/kind (drives the cartoon cast)
    thumbnail_text: str = ""   # 2-4 punchy words printed on the thumbnail (complements, never repeats, the title)

    @property
    def full_narration(self) -> str:
        return " ".join(scene.narration for scene in self.scenes)


def _daily_quota_exhausted_message(response) -> "str | None":
    """If this 429 response is a genuine daily quota exhaustion (as opposed to
    a short-lived per-minute rate limit, which IS worth retrying), returns a
    clear diagnostic message; otherwise returns None.

    Real incident this guards against: a scheduled run failed with a 429,
    which _RETRY_STATUSES treated identically to a transient rate limit -
    retrying with exponential backoff for minutes on something that can't
    possibly succeed until the quota resets (once per day). The response
    body is explicit about which case it is: a genuine daily cap comes back
    with a quotaId containing 'PerDay' (e.g.
    'GenerateRequestsPerDayPerProjectPerModel-FreeTier') - Google's own
    suggested retryDelay in the body (often just a few seconds) is a generic
    default for 429s generally and does NOT mean the daily quota will have
    refreshed by then, so it should not be trusted to decide whether to
    retry."""
    if response.status_code != 429:
        return None
    try:
        violations = response.json()["error"]["details"]
    except (ValueError, KeyError, TypeError, IndexError):
        return None
    for detail in violations:
        for violation in detail.get("violations", []):
            quota_id = violation.get("quotaId", "")
            if "PerDay" in quota_id:
                return (
                    f"Gemini API daily quota exhausted ({quota_id}, limit "
                    f"{violation.get('quotaValue', '?')} requests/day for "
                    f"model {violation.get('quotaDimensions', {}).get('model', MODEL)}). "
                    "This will not resolve by retrying within the same day - it needs "
                    "either waiting for the daily reset or upgrading the API key off the "
                    "free tier (https://ai.google.dev/gemini-api/docs/rate-limits)."
                )
    return None


def _call_gemini(prompt: str, function_name: str, parameters: dict, config: PipelineConfig, max_output_tokens: int) -> dict:
    """Calls Gemini with a single forced function call and returns its args."""
    if not config.secrets.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to youtube-automation/.env "
            "(copy .env.example first)."
        )

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{
            "function_declarations": [{
                "name": function_name,
                "description": f"Return the finished {function_name.replace('emit_', '')}.",
                "parameters": parameters,
            }],
        }],
        "tool_config": {
            "function_calling_config": {"mode": "ANY", "allowed_function_names": [function_name]},
        },
        # thinkingLevel="minimal": this task needs direct structured
        # generation, not extended reasoning, and leaving thinking on ate a
        # large fraction of max_output_tokens on "thoughts" rather than the
        # actual script. Gemini 3.x replaced the old integer thinkingBudget
        # (Gemini 2.x) with this string enum (minimal/low/medium/high) -
        # sending thinkingBudget to a Gemini 3 model is rejected outright
        # with a generic "400 INVALID_ARGUMENT", which is what broke every
        # scheduled run when gemini-flash-latest rolled onto Gemini 3.5.
        "generationConfig": {"maxOutputTokens": max_output_tokens, "thinkingConfig": {"thinkingLevel": "minimal"}},
    }

    last_error = None
    response = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(
                API_URL,
                params={"key": config.secrets.gemini_api_key},
                json=body,
                timeout=180,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = str(exc)
            if attempt < _MAX_RETRIES:
                time.sleep(min(2 ** attempt, _MAX_BACKOFF_SECONDS))
                continue
            raise RuntimeError(
                f"Gemini API request timed out after {_MAX_RETRIES + 1} attempts: {last_error}"
            ) from exc

        if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            quota_message = _daily_quota_exhausted_message(response)
            if quota_message:
                raise RuntimeError(quota_message)
            last_error = response.text
            time.sleep(min(2 ** attempt, _MAX_BACKOFF_SECONDS))
            continue
        break

    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:2000]}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {data}")

    for part in candidates[0].get("content", {}).get("parts", []):
        call = part.get("functionCall")
        if call and call.get("name") == function_name:
            return call.get("args", {})

    if candidates[0].get("finishReason") == "MAX_TOKENS" and max_output_tokens < _MODEL_MAX_OUTPUT_TOKENS:
        # The function call was cut off mid-JSON (nothing usable comes back). Retry with a bigger budget
        # instead of failing the whole run; doubling reaches the model ceiling in a couple of steps.
        bigger = min(_MODEL_MAX_OUTPUT_TOKENS, max_output_tokens * 2)
        logger.warning("Gemini hit MAX_TOKENS at %d output tokens without finishing %s - retrying with %d.",
                       max_output_tokens, function_name, bigger)
        return _call_gemini(prompt, function_name, parameters, config, bigger)

    raise RuntimeError(f"Gemini did not call {function_name}: {data}")


def _script_length_params(target_seconds: int, wpm: int = 165) -> Tuple[int, int, int]:
    """Returns (target_words, suggested_scenes, max_output_tokens) for a
    given target duration. Pulled out of generate_script so the actual
    numbers a given target_seconds produces are directly testable, without
    needing to mock the whole Gemini call chain."""
    # Words-per-minute assumption used to convert a target duration into a
    # target word count. Was 140 (a generic "safe average narration pace"
    # guess) until real evidence showed it was too slow for this specific
    # setup: tts.py applies per-scene rate boosts on top of the base voice
    # rate (+15% on hook scenes, +5% on build scenes, which dominate a
    # script's scene count), so actual spoken pace runs measurably faster
    # than a flat, unboosted assumption. A real published video that had
    # cleared the (then-current) word-count retry threshold still rendered
    # at ~154 words/minute once actually spoken - i.e. even AFTER passing
    # the check meant to catch this, real pace still exceeded the 140
    # assumption by ~10%. Raised to 165 (headroom above 154, not just
    # matching it exactly) so target_words - and everything derived from it,
    # including the retry threshold - reflects real achieved pace rather
    # than reproducing the same gap the retry mechanism exists to catch.
    target_words = max(60, round(target_seconds * wpm / 60))
    # ~25 words per scene keeps each one a genuine "1-2 sentences a few seconds
    # long" beat rather than a paragraph - matters a lot once target_words
    # gets into longform territory (a fixed "6-9 scenes" would otherwise force
    # multi-sentence walls of narration per scene, or the model quietly
    # ignoring the length target to keep scenes short).
    # Both caps below (scene count, output tokens) used to be tuned for a
    # ~20-minute longform target and worked fine at that length in
    # production - they were left at their smaller values from when
    # target_seconds was temporarily reduced to ~7 minutes, which silently
    # capped every longform video back down regardless of what
    # config.yaml's target_seconds actually asked for. Raised back up
    # (with headroom) rather than exactly matching today's target, so this
    # isn't a recurring one-off fix if target_seconds moves again later.
    # This model's real ceiling is 65,536 output tokens (confirmed against
    # Google's published model card for both gemini-3.5-flash and the
    # -lite variant this is now pinned to - same ceiling on both) - 8000
    # was never actually close to that limit, it was just an unrelated
    # conservative guess.
    suggested_scenes = max(6, min(160, round(target_words / (12 if target_seconds <= 90 else 25))))   # Shorts: ~4s scenes keep the visuals moving
    # ~8 tokens per narration word, not 4: the forced function call is JSON, and every scene also carries
    # role/visual_keywords/on_screen_text/setting/action/mood/time_of_day. At 4/word a ~3100-word longform
    # (12,900 tokens) hit finishReason=MAX_TOKENS mid-JSON and returned no function call at all, which
    # crashed three scheduled longform runs in a row (2026-11-04..06).
    max_output_tokens = min(_MODEL_MAX_OUTPUT_TOKENS, max(2000, round(target_words * 8) + 2000))
    return target_words, suggested_scenes, max_output_tokens


_LENGTH_RETRIES = 5
_MODEL_MAX_OUTPUT_TOKENS = 65536   # gemini-3.5-flash(-lite) output ceiling
_EXTEND_PASSES = 4
EMIT_EXTRA_SCENES = "emit_extra_scenes"
# Same scene shape as the full script, just without title/description/tags.
EXTEND_SCHEMA = {
    "type": "object",
    "properties": {"scenes": SCRIPT_SCHEMA["properties"]["scenes"]},
    "required": ["scenes"],
}


def _draft_text(data: dict) -> str:
    return "\n\n".join(s["narration"].strip() for s in data["scenes"])


_MIN_ROLE_REPAIR_WORDS = 15


def _repair_roles(data: dict) -> dict:
    """The prompt always asks for first scene=hook and last scene=insight, but
    the model sometimes writes exactly that and still tags the last scene
    "build" - which made quality_check.py fail otherwise-fine videos and
    upload them as private. Fix the labels when the scene is clearly real
    narration; leave genuinely empty/tiny scenes alone so the gate still
    catches truncated output."""
    scenes = data.get("scenes") or []
    if not scenes:
        return data
    first, last = scenes[0], scenes[-1]
    if first.get("role") != "hook" and len(first["narration"].split()) >= _MIN_ROLE_REPAIR_WORDS:
        logger.warning("First scene was tagged role=%r; relabeling as 'hook'.", first.get("role"))
        first["role"] = "hook"
    if last.get("role") != "insight" and len(last["narration"].split()) >= _MIN_ROLE_REPAIR_WORDS:
        logger.warning("Last scene was tagged role=%r; relabeling as 'insight'.", last.get("role"))
        last["role"] = "insight"
    return data


def _extend_to_length(data: dict, topic: str, min_words: int, config: PipelineConfig, max_output_tokens: int) -> dict:
    """Last resort when re-asking for a full, longer script still undershoots:
    rewriting the whole thing in one go keeps coming back ~25% short (the model
    stops when the story "feels" complete), so instead ask for ONLY the missing
    material - extra build scenes with new specifics - and splice them in before
    the final insight scene. Each pass adds roughly the shortfall, so a few
    passes reliably reach the same length bar the quality gate enforces. The
    gate's thresholds are unchanged; this just makes generation meet them."""
    for n in range(1, _EXTEND_PASSES + 1):
        words = sum(len(sc["narration"].split()) for sc in data["scenes"])
        if words >= min_words:
            break
        need = min_words - words + 120
        prompt = f"""You are extending a documentary-style narration about: {topic}
Title: {data["title"]}

The script below is {words} words but needs at least {min_words}. Write NEW build scenes totalling about
{need} words (roughly {max(2, need // 180)} scenes of 120-220 words each) that add material the script does NOT
already cover: more specific people, dates, numbers, decisions, near-misses, consequences and aftermath.
They will be inserted just before the final insight scene, so keep the same voice and tense, make them
flow from the existing build, and do not repeat or restate anything already written. No markdown.

EXISTING NARRATION:
---
{_draft_text(data)}
---"""
        try:
            extra = _call_gemini(prompt, EMIT_EXTRA_SCENES, EXTEND_SCHEMA, config, max_output_tokens)
        except Exception as exc:  # noqa: BLE001 - never lose a good script over a failed top-up
            logger.warning("Length extension pass %d failed (%s); keeping the script as-is.", n, exc)
            break
        existing = {" ".join(sc["narration"].lower().split()).rstrip(".!?") for sc in data["scenes"]}
        new_scenes = []
        for sc in extra.get("scenes", []):
            text = sc.get("narration", "").strip()
            key = " ".join(text.lower().split()).rstrip(".!?")
            if len(text.split()) < 25 or key in existing:
                continue
            existing.add(key)
            new_scenes.append({
                "role": "build", "narration": text,
                "visual_keywords": list(sc.get("visual_keywords") or [topic])[:6],
                "on_screen_text": sc.get("on_screen_text", "") or "",
            })
        if not new_scenes:
            logger.warning("Length extension pass %d returned nothing usable.", n)
            break
        data["scenes"] = data["scenes"][:-1] + new_scenes + data["scenes"][-1:]
        logger.info("Length extension pass %d added %d scenes (%d words).", n, len(new_scenes),
                    sum(len(sc["narration"].split()) for sc in new_scenes))
    return data


def _winning_titles_block(format_name: str) -> str:
    """Prompt block listing this channel's own best-performing titles, so new titles learn from real view data."""
    try:
        from .growth_ledger import top_titles
        formats = ("shorts", "teaser") if format_name in ("shorts", "teaser") else ("longform",)
        best = top_titles(formats, n=5)
    except Exception:  # noqa: BLE001 - optional signal; never block a script over it
        return ""
    if not best:
        return ""
    lines = "\n".join(f'- "{r["title"]}" ({r["views"]} views)' for r in best)
    return f"""
WHAT ALREADY WORKS ON THIS CHANNEL - these real titles got the most views here:
{lines}
Study what they share (a specific person/place/number, a strange concrete detail, an unresolved gap) and give this video's
title the same pull. Never copy or lightly reword them, and stay on this video's topic.
"""


def insert_cta_break(script: "Script", text: str) -> bool:
    """Puts a short spoken like-and-subscribe beat right after the hook (a scene of its own, so it gets voiced, captioned
    and drawn like any other). It copies the hook's setting/people so the picture does not jump. Idempotent; returns
    whether it inserted anything. Only meaningful for a script that starts with its hook and has a story after it."""
    scenes = script.scenes
    if len(scenes) < 3 or scenes[0].role != "hook" or not text.strip():
        return False
    if any(getattr(s, "kind", "") == "cta_break" for s in scenes):
        return False
    hook = scenes[0]
    scenes.insert(1, Scene(
        narration=text.strip(), visual_keywords=list(hook.visual_keywords), role="build",
        setting=hook.setting, action="talk", mood="neutral", time_of_day=hook.time_of_day,
        on_screen=list(hook.on_screen), prop=hook.prop, kind="cta_break",
    ))
    return True


SHORT_MAX_OVERSHOOT = 1.2   # a Short may run at most 20% over its word budget before it gets tightened


def _tighten_short(data: dict, target_words: int, config: PipelineConfig, max_output_tokens: int) -> dict:
    """Shorts kept coming back 1.5-2.5x their budget (55-113s against a 40s target), and a long Short loses the
    completion/replay rate the Shorts feed ranks on. One Gemini pass cuts it to budget; the original is kept
    unless the cut is genuinely shorter, still long enough, and keeps the same opening line."""
    words = sum(len(s["narration"].split()) for s in data["scenes"])
    if words <= round(target_words * SHORT_MAX_OVERSHOOT):
        return data
    first_line = data["scenes"][0]["narration"].strip()
    ending = ("Keep the final unresolved cliffhanger and the call-to-action to the full video; never reveal the outcome."
              if config.video.format == "teaser" else
              "Keep the final scene's loop back to the opening and any call-to-action it ends with.")
    prompt = f"""Tighten this vertical YouTube Short to about {target_words} words of narration total (it is {words}).
Rules: keep scene 1's narration EXACTLY as written: "{first_line}". {ending} Cut background, repetition, filler and the weakest middle beats - never the
strangest concrete facts. Fewer, punchier scenes are fine. Keep title, description, tags, thumbnail_text and
title_options as they are. Every scene keeps its role, visual_keywords, on_screen_text, setting, action, mood and
time_of_day. No markdown. Call {EMIT_SCRIPT} with the full result.

CURRENT SCRIPT (JSON):
{json.dumps(data, ensure_ascii=False)}"""
    try:
        cut = _call_gemini(prompt, EMIT_SCRIPT, SCRIPT_SCHEMA, config, max_output_tokens)
        cut_words = sum(len(s["narration"].split()) for s in cut["scenes"])
    except Exception as exc:  # noqa: BLE001 - a failed tighten keeps the original script
        logger.warning("Shorts tighten pass failed (%s); keeping the %d-word script.", str(exc)[:200], words)
        return data
    min_words = round(target_words * MIN_TARGET_LENGTH_FRACTION)
    if (len(cut["scenes"]) >= 3 and min_words <= cut_words < words
            and cut["scenes"][0]["narration"].strip().split()[:4] == first_line.split()[:4]):
        logger.info("Tightened Short from %d to %d words (budget %d).", words, cut_words, target_words)
        for key in ("title", "description", "tags", "thumbnail_text", "title_options", "characters"):
            if key in data:
                cut[key] = data[key]
        return cut
    logger.warning("Shorts tighten pass not usable (%d words, %d scenes); keeping the original.", cut_words, len(cut["scenes"]))
    return data


def generate_script(topic: str, config: PipelineConfig, source: "dict | None" = None) -> Script:
    """Ask Gemini to write a full scene-by-scene script for one video.

    `source` (teaser format only) is the ledger record of the longform being promoted: its title and opening narration.
    """
    target_words, suggested_scenes, max_output_tokens = _script_length_params(config.video.target_seconds, config.voice.words_per_minute)

    # Shorts use these directly for Pexels stock-footage search; longform
    # uses them too, for procedural_illustration.py's setting/outfit/headwear/
    # mood keyword matching, and both formats use them for sound_effects.py's
    # ambience keyword matching - concrete, topic-specific nouns work better
    # than abstract mood words for all three purposes.
    visual_keyword_guidance = (
        "each scene visual_keywords that a stock-footage search engine could use to find "
        f"matching {config.visuals.orientation}-orientation footage that actually depicts this "
        "scene's specific content (the subject, era, location, objects involved) - concrete, "
        "filmable nouns tied to the topic, not abstract ideas or generic mood words"
    )

    shorts_rules = ""
    teaser_override = ""
    if config.video.format == "teaser":
        src_title = (source or {}).get("title") or topic
        src_seed = (source or {}).get("seed") or ""
        seed_block = (f"\nThe real video opens like this (stay consistent with it, never contradict it):\n---\n{src_seed}\n---\n" if src_seed
                      else "\nOnly use facts you are certain are accurate about this story; do not invent details.\n")
        shorts_rules = f"""
CLIFFHANGER TEASER RULES (this vertical Short is the opening of a longer story; the full story is a separate, much longer
video already on this channel titled "{src_title}"):
- The first sentence is 8 words or fewer and states the strangest concrete fact of the story.
- Every sentence is a new reveal or escalation. No background, no history lesson.
- Tell the story forward and STOP at its single most gripping unresolved moment, right before the answer. NEVER reveal the
  outcome, culprit, explanation or twist - not even hinted at as solved. The viewer must NEED the rest.
- The final scene before the call-to-action is one short line that cuts off mid-tension (an unanswered question or "And then they opened it.").
- Do NOT loop back to the first line. Do NOT summarise or draw a lesson. Do NOT read a URL aloud.
- Title: a curiosity gap that withholds the outcome (a specific name/place/number plus an open question).{seed_block}"""
        teaser_override = """
FORMAT OVERRIDE FOR THIS SHORT (wins over the HOOK->BUILD->INSIGHT, 'perspective shift' and 'comment question' instructions above):
the last scene must be the unresolved cliffhanger, NOT a perspective shift, summary or comment question. Still tag it role=insight.
"""
    if config.video.format == "shorts":
        shorts_rules = """
SHORTS RULES (this is a vertical Short, not a mini documentary):
- ONE idea only. The first sentence is 8 words or fewer and states the strangest concrete fact ("Three men vanished from a locked island.").
- No context, no history lesson, no setup - the viewer decides in under 3 seconds. Every sentence must be a new reveal or escalation.
- The final line loops back to the first line so the Short replays naturally, then says: "Follow for the full story on YouTube."
"""
    prompt = f"""You are writing a {config.video.format} YouTube video script for a faceless channel.
This channel's videos need to read as a genuinely produced mini-documentary with a point of
view, not a text-to-speech slideshow of disconnected trivia - YouTube treats the latter as
low-value "reused/duplicative content" and won't monetize it, so the connective analysis
matters as much as the facts themselves.

Channel: {config.channel.name}
Niche: {config.channel.niche}
Audience: {config.channel.audience}
Tone: {config.channel.tone}
Topic for this video: {topic}

Write the title first, then a script that delivers on it. This channel only ships 10/10,
"how did I not know this" videos - never a generic listicle or topic label ("5 Facts About Rome",
"World War II: A Documentary"). Pick whichever specific, genuinely surprising angle fits this
particular topic best:
- Cause -> consequence: one concrete trigger (a death, a single choice, one mistake, one
  discovery) and the much bigger, surprising thing it caused - "How did the death of [a specific
  named person] cause [a specific named event]?"
- Immersive daily-life curiosity: what it actually felt like to live it - "What Was It Really
  Like to Be a Gladiator in Ancient Rome?"
- Myth/legend retold as a gripping real story - "The Greek Myth That Terrified an Entire
  Civilization"
- A hidden truth or reveal - "The Secret the Pharaohs Didn't Want Anyone to Know"
Whichever shape you use, the title must be specific (named people/places/events, not vague
categories) and the hook scene's first sentence must open by directly delivering on that exact
promise - a title/thumbnail that oversells what the video actually opens with is the single
biggest reason a video's retention (and therefore YouTube's willingness to keep recommending it)
collapses in the first seconds.

HOOK CRAFT (the first 15 seconds decide whether anyone watches; most of this channel's viewers leave here):
- The very first sentence is 14 words or fewer and names something SPECIFIC (a person, place, number or object). Open IN the moment -
  the single most striking concrete image or event, mid-action - BEFORE any background.
- NEVER open with throat-clearing: not "In [year]...", "Welcome", "Today", "Have you ever wondered", "Imagine", "Did you know",
  "Let's", "Picture this", "This is the story of". Start with the event itself.
- Sentence 2 states the unanswered question or the stakes. Sentence 3 promises a payoff that is specific and delayed
  ("The answer was in a letter nobody opened for 80 years.") without claiming anything unproven.
- The whole hook scene is 35 words or fewer. Scene 2 must ESCALATE (new twist), never explain the hook.
- Concrete beats abstract: "a table set for dinner, clocks stopped" beats "a mysterious disappearance".
{shorts_rules}
{_winning_titles_block(config.video.format)}TITLES: also fill `title_options` with 3 DIFFERENT title angles (curiosity gap, a specific number or name, an unanswered question).
Each is 35-65 characters, specific, and never states an unproven claim as fact.

RETENTION ENGINEERING - DO NOT SKIP THESE:
1. HOOK (scene 1): Open with a PATTERN INTERRUPT - a statement that violates expectations.
   Examples: "The Roman Empire didn't fall. It was murdered." / "Everything you know about
   [topic] is wrong." / "In 1913, a janitor solved a problem that killed 400,000 people."
   Then immediately open a CURIOUSITY LOOP: "And the reason why will change how you see
   [topic] forever." The hook's job is not to explain - it's to create a GAP the viewer MUST
   close by watching.

2. THE 20-30s CLIFF (scene 2): This is the SECOND RETENTION DROP-OFF. The hook paid off
   the title's promise; now the viewer asks "okay, but is there MORE?" Scene 2 MUST introduce
   a FRESH ESCALATION - a twist, reversal, or complication that was NOT in the hook. Use
   phrases like "But that's only half the story..." / "What happened next was worse..." /
   "And that's when they realized..." - never just elaborate on the hook.

3. OPEN LOOPS EVERY 45-60s: Each build scene should OPEN a new curiosity loop before closing
   the previous one. "We'll come back to that. But first..." / "The reason why is even stranger..."
   This chains retention - the viewer stays to close the NEXT loop, which opens ANOTHER.

4. THE INSIGHT (final scene): Don't just summarize. Deliver a PERSPECTIVE SHIFT - a new lens
   that reframes everything the viewer just watched. "This wasn't really about [topic]. It was
   about [deeper truth]." That's what earns the share, the subscribe, the algorithm boost.
   Finish with ONE specific, easy-to-answer question that invites a comment ("Do you think it was an accident, or something worse? Tell me below.").

SCENE DIRECTION: for EVERY scene fill in setting, action, mood and time_of_day. The setting must match
where that scene's narration physically takes place (a trench scene is battlefield, a general's briefing is
warroom, a cruise-ship scene is shipdeck). Use action=talk for most scenes; reserve fight and crowd for the
few scenes where combat or a large crowd is genuinely the subject, and never use the same non-talk action
in back-to-back scenes.

CHARACTERS: list the 2-5 real people of this story in `characters` with their true gender, a historically accurate
skin tone, age and kind (soldier/royal/scholar/...). In EVERY scene, `on_screen` names who is visible (1-3 people,
main one first - include a second person whenever two people interact), and `prop` names what the main person
holds when the narration involves it (a rifle for a WW1 soldier, a letter, a map, a book, a sword in ancient or
medieval times). Never give a prop from the wrong era (no guns before 1600, no swords in modern scenes).

FACTUAL INTEGRITY (non-negotiable): when the story involves real people, unsolved cases, or disputed
events, never state an unproven claim as established fact - in the TITLE, the hook, or the narration.
Attribute it ("witnesses claimed", "investigators believed", "allegedly") and frame open questions as
questions. Titles must not use "proves", "proof", "confirmed", "exposed" or "the real truth" for anything
that is not settled fact.

Write a script of roughly {target_words} words of total narration ({config.video.target_seconds}
seconds at a natural speaking pace), split into roughly {suggested_scenes} short scenes with
this shape:
- One "hook" scene (first): pattern interrupt + curiosity gap that earns the runtime.
- {suggested_scenes - 2}+ "build" scenes: connected facts, each opening a new loop before
  closing the last. Use connective tissue ("but here's the twist...", "which raises the
  question...", "and that's the part most people get wrong..."). If the most obvious version of
  this story feels "finished" well before {target_words} words, that's a sign to go deeper, not
  a sign the story is done - add texture: what specific people involved were thinking and feeling
  in the moment, the smaller decisions and near-misses along the way, what almost happened
  instead, the aftermath and how it rippled outward, how contemporaries reacted. A real target
  this channel has hit before: coming in well short of {target_words} words undermines the
  format this channel runs on and the video won't ship as-is - depth and richness of a single
  well-chosen story beats moving on to a new one early.
- One "insight" scene (last): perspective shift that reframes the whole story.

Each scene's narration should target {config.video.target_scene_duration} seconds of speech 
({config.video.min_scene_duration}-{config.video.max_scene_duration} seconds acceptable) — 
do not write paragraph-length narration for a single scene, split it into more scenes instead. Give
{visual_keyword_guidance}.
Do not use markdown in the narration. Only state facts you're confident are accurate; do not
fabricate statistics or quotes.{teaser_override}
Call emit_script with the final result."""

    data = _call_gemini(prompt, EMIT_SCRIPT, SCRIPT_SCHEMA, config, max_output_tokens)

    word_count = sum(len(s["narration"].split()) for s in data["scenes"])
    min_acceptable_words = round(target_words * MIN_TARGET_LENGTH_FRACTION)
    if word_count < min_acceptable_words:
        # The prompt above only asks for "roughly" the target length - a soft
        # ask the model doesn't always honor (see MIN_TARGET_LENGTH_FRACTION's
        # docstring for the real incident this guards against). Retrying with
        # the actual shortfall spelled out explicitly is cheap compared to
        # shipping a video at half its requested length, or worse, having
        # quality_check.py catch it only after TTS/rendering has already run.
        # Up to 3 retries (4 attempts total, up from 2/3 after the channel
        # went 4 real days without a public video - see
        # MIN_TARGET_LENGTH_FRACTION's docstring): a real incident's first
        # retry brought word count from ~1250 to 1915 against the bar in
        # effect at the time - genuine, substantial improvement that still
        # narrowly missed, so more attempts are worth it rather than
        # accepting a near-miss, especially now the bar itself (0.85, up
        # from 0.7) and target_words (165 wpm, up from 140) are both higher.
        best_data, best_word_count = data, word_count
        for attempt in range(1, _LENGTH_RETRIES + 1):
            logger.warning(
                "Script at %d words, under this %ds video's target of ~%d words - "
                "retry %d/%d with a reinforced prompt.",
                best_word_count, config.video.target_seconds, target_words, attempt, _LENGTH_RETRIES,
            )
            reinforced_prompt = prompt + f"""

IMPORTANT: A previous attempt at this exact prompt came back with only {best_word_count} words of
narration - well short of the ~{target_words} words this video needs. Do not stop the story early
just because the most obvious version of it feels complete - go deeper into the specific people,
decisions, near-misses, and aftermath involved (see the guidance above on adding texture rather
than moving on early). This attempt must reach at least {min_acceptable_words} words of total
narration.

Here is the narration of the best previous draft ({best_word_count} words). Keep the same story and
the same hook -> build -> insight structure, but EXPAND it: add the missing depth, specifics and
aftermath until it clears {min_acceptable_words} words. Do not shorten or drop anything that is
already here.
---
{_draft_text(best_data)}
---"""
            try:
                retry_data = _call_gemini(reinforced_prompt, EMIT_SCRIPT, SCRIPT_SCHEMA, config, max_output_tokens)
            except Exception as exc:  # noqa: BLE001 - a failed retry must never throw away the draft we already have
                # Every failed longform run on 2026-11-04..06 died HERE (MAX_TOKENS / a 503 that outlasted the
                # backoff) while already holding a usable first draft. Keep the best draft and move on - the
                # extension pass below and quality_check.py still enforce the length bar.
                logger.warning("Length retry %d failed (%s) - keeping the best draft so far (%d words).",
                               attempt, str(exc)[:300], best_word_count)
                break
            retry_word_count = sum(len(s["narration"].split()) for s in retry_data["scenes"])
            if retry_word_count > best_word_count:
                logger.info("Retry %d produced %d words (up from %d).", attempt, retry_word_count, best_word_count)
                best_data, best_word_count = retry_data, retry_word_count
            else:
                logger.warning(
                    "Retry %d did not improve length (%d words vs best-so-far %d).",
                    attempt, retry_word_count, best_word_count,
                )
            if best_word_count >= min_acceptable_words:
                break
        data = best_data
        if best_word_count < min_acceptable_words:
            logger.warning(
                "Still under target after retries (%d words, best of %d attempts) - "
                "keeping the best attempt; quality_check.py will catch it if it's still too short.",
                best_word_count, attempt + 1,
            )
            data = _extend_to_length(data, topic, min_acceptable_words, config, max_output_tokens)

    if config.video.format in ("shorts", "teaser"):
        data = _tighten_short(data, target_words, config, max_output_tokens)

    data = _repair_roles(data)

    scenes = [
        Scene(
            narration=s["narration"].strip(),
            visual_keywords=list(s["visual_keywords"]),
            role=s.get("role", "build"),
            on_screen_text=s.get("on_screen_text", "") or "",
            setting=s.get("setting", "") or "", action=s.get("action", "") or "",
            mood=s.get("mood", "") or "", time_of_day=s.get("time_of_day", "") or "",
            on_screen=[n for n in (s.get("on_screen") or []) if isinstance(n, str)][:3], prop="" if (s.get("prop") or "none") == "none" else s["prop"],
        )
        for s in data["scenes"]
    ]

    return Script(
        topic=topic,
        title=data["title"].strip(),
        description=data["description"].strip(),
        tags=[t.strip() for t in data["tags"]],
        scenes=scenes,
        thumbnail_text=(data.get("thumbnail_text") or "").strip(),
        characters=[c for c in (data.get("characters") or []) if isinstance(c, dict) and c.get("name")][:6],
        title_options=[t.strip() for t in (data.get("title_options") or []) if isinstance(t, str) and t.strip()][:5],
    )


def _call_gemini_grounded(prompt: str, config: PipelineConfig, max_output_tokens: int) -> str:
    """Calls Gemini with Google Search grounding enabled and returns the plain
    text response (real, current web results - not just the model's training
    knowledge). No function calling here: the stable generateContent REST API
    this project uses (see the module docstring) only supports combining
    google_search grounding with *forced* function calling via Gemini's newer
    Interactions API, which is still Preview/Gemini-3-only - mixing them into
    one _call_gemini-style request would risk a 400 on the stable endpoint.
    Kept as a separate, deliberately simple call; brainstorm_trending_topics()
    below is the two-step caller that turns this free-text output into a
    structured topic list via the existing _call_gemini function-calling path.
    """
    if not config.secrets.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to youtube-automation/.env "
            "(copy .env.example first)."
        )

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": max_output_tokens, "thinkingConfig": {"thinkingLevel": "minimal"}},
    }

    last_error = None
    response = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(
                API_URL,
                params={"key": config.secrets.gemini_api_key},
                json=body,
                timeout=180,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = str(exc)
            if attempt < _MAX_RETRIES:
                time.sleep(min(2 ** attempt, _MAX_BACKOFF_SECONDS))
                continue
            raise RuntimeError(
                f"Gemini grounded search request timed out after {_MAX_RETRIES + 1} attempts: {last_error}"
            ) from exc

        if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            quota_message = _daily_quota_exhausted_message(response)
            if quota_message:
                raise RuntimeError(quota_message)
            last_error = response.text
            time.sleep(min(2 ** attempt, _MAX_BACKOFF_SECONDS))
            continue
        break

    if response.status_code != 200:
        raise RuntimeError(f"Gemini grounded search error {response.status_code}: {response.text[:2000]}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini grounded search returned no candidates: {data}")

    text = "".join(
        part.get("text", "") for part in candidates[0].get("content", {}).get("parts", [])
    ).strip()
    if not text:
        raise RuntimeError(f"Gemini grounded search returned no text: {data}")
    return text


def brainstorm_trending_topics(config: PipelineConfig, existing: List[str], count: int = 5) -> List[str]:
    """Like brainstorm_topics(), but grounded in real current trending stories/
    news via Google Search, rather than Gemini's training-knowledge-only ideas.
    Two-step: (1) a grounded search call finds what's genuinely trending a lot
    right now (not narrowly filtered to the niche label - see the prompt for
    why), (2) that real, current-events context is handed to the existing
    forced-function-call path to shape it into the same dramatic, hook-forward
    topic format brainstorm_topics() produces - see that function's prompt for
    the shared topic-selection criteria.
    """
    search_prompt = f"""Search for what's genuinely trending A LOT right now (today) - broadly, not limited to
any narrow category. This channel makes {config.channel.tone} narrative videos for {config.channel.audience},
so lean toward the kind of trending stories that could sustain a substantial, genuinely interesting
narrative video: major historical anniversaries getting renewed attention, significant rediscoveries
or new evidence in a known story, a big documentary/book release reviving interest in something, a
genuinely major current event with real depth and a strong angle - basically the internet's actual big
talking points right now, not this week's niche noise.

Do NOT include unimportant or shallow trending stuff - skip minor celebrity gossip, fleeting memes,
routine sports results, minor product launches, or anything too thin to sustain real depth. Only list
things substantial enough that a person could stay interested in a full 20-minute deep dive on it.

List up to 10 real, specific, currently-relevant stories or angles you found, each as one line: a
concrete name/event/story plus a one-sentence note on why it's trending right now and why it has
enough real substance/depth for a long-form video. Only include things you actually found evidence
of being current - do not invent or guess at trends."""

    try:
        grounded_findings = _call_gemini_grounded(search_prompt, config, max_output_tokens=1800)
    except Exception as exc:
        raise RuntimeError(f"Grounded trending search failed: {exc}") from exc

    schema = {
        "type": "object",
        "properties": {
            "topics": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topics"],
    }

    used_list = "\n".join(f"- {t}" for t in existing) or "(none yet)"
    prompt = f"""Channel niche (a loose starting point, not a hard filter): {config.channel.niche}
Channel tone: {config.channel.tone}
Audience: {config.channel.audience}

Already-used topics (do not repeat these or close variants):
{used_list}

Here is a real, current-events research pass on what's genuinely trending a lot right now (from a
live web search, not guesswork) - deliberately not narrowed to the niche above, since the goal is
whatever's actually a big current talking point, as long as it's substantial enough for a real video:

{grounded_findings}

From this, pick and shape {count} video topics. The topic doesn't need to fit the niche label
narrowly - what matters is (a) it's genuinely one of the bigger current trending talking points from
the research above, (b) it's substantial enough to sustain ~20 minutes of genuinely interesting
narrative content (skip anything too thin, trivial or shallow even if it's technically trending),
and (c) it meets this channel's usual bar - bias hard toward genuinely dramatic, high-stakes,
shocking, vivid, or emotionally charged angles over bland "fun fact" trivia or generic topic labels.

TOPIC SELECTION CRITERIA (each topic MUST score high on):
1. CURIOSITY GAP: Can the title alone create "I NEED to know" urgency?
2. VISUAL THUMBNAIL POTENTIAL: One concrete, striking image that reads at 160x90px
3. EMOTIONAL STAKES: Life/death, freedom/slavery, truth/lie, survival/extinction
4. NARRATIVE MOMENTUM: A clear beginning->middle->end with escalation
5. UNIQUENESS: Not a Wikipedia summary - a SPECIFIC untold angle
6. DEPTH: Enough real substance to fill ~20 minutes without padding or repetition

Each topic needs a clear, specific, named anchor (a person, role, place, or event) - not a vague
category on its own. Avoid anything copyrighted or that would require paid licensing to depict.
If fewer than {count} of the research findings above are genuinely substantial and interesting
enough, it's fine to return fewer than {count} rather than force a weak or trivial one in. Call
{EMIT_TOPICS} with the result."""

    data = _call_gemini(prompt, EMIT_TOPICS, schema, config, max_output_tokens=600)
    topics = list(data["topics"])
    if not topics:
        raise RuntimeError("Grounded trending search found nothing that fit this channel's niche well enough.")
    return topics


def brainstorm_followups(config: PipelineConfig, niche: str, winner_title: str, winner_views: int,
                         existing: List[str], count: int = 3) -> List[str]:
    """Topics that repeat a breakout video's winning formula: same niche, same hook pattern, different stories
    (plus one that goes deeper into the winner's own story). Viral channels grow by doubling down on what hit."""
    schema = {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "string"}}}, "required": ["topics"]}
    used_list = "\n".join(f"- {t}" for t in existing[-60:]) or "(none yet)"
    prompt = f"""Channel niche: {niche}

This video BROKE OUT on our channel ({winner_views} views - many times our typical video):
"{winner_title}"

Suggest {count} new video topics that repeat what made it work. First work out its formula in your head: the kind of
protagonist (an ordinary or unlikely person? a famous one caught off guard?), the hook shape (a tiny cause with a
massive consequence? a mystery with a chilling detail?), the era/region and the emotional stakes. Then:
- Topic 1: a deeper or untold angle of the SAME real story (what happened next, the person nobody remembers in it,
  the detail that changes how it reads) - a genuinely new video, not a retelling.
- The others: DIFFERENT real stories with the same formula, equally specific and surprising.
Each topic is one sentence with a clear named anchor (person, place, date) and one concrete, visual moment.
Only real, verifiable history; never state an unproven claim as fact.

Already-used topics (do not repeat these or close variants):
{used_list}

Call {EMIT_TOPICS} with the result."""
    data = _call_gemini(prompt, EMIT_TOPICS, schema, config, max_output_tokens=1200)
    return [t.strip() for t in data.get("topics", []) if isinstance(t, str) and t.strip()][:count]


def brainstorm_topics(config: PipelineConfig, existing: List[str], count: int = 5) -> List[str]:
    """Ask Gemini for fresh topic ideas that avoid what's already been made."""
    schema = {
        "type": "object",
        "properties": {
            "topics": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topics"],
    }

    used_list = "\n".join(f"- {t}" for t in existing) or "(none yet)"
    prompt = f"""Channel niche: {config.channel.niche}
Audience: {config.channel.audience}

Already-used topics (do not repeat these or close variants):
{used_list}

Suggest {count} new video topics for this channel. Bias hard toward genuinely dramatic,
high-stakes, shocking, vivid, or emotionally charged stories over bland "fun fact" trivia or
generic topic labels - the kind of premise that makes someone stop scrolling. Depending on what
best fits this niche, each topic should be one of:
- A specific cause -> surprising consequence (one death, decision, or mistake that led to
  something much bigger than it sounds like it should have)
- A vivid, specific slice of what daily life was actually like for someone in a particular time
  and place (a specific role, a specific empire, a specific moment)
- A specific myth or legend with real dramatic stakes, told as a gripping story
- A real person facing a real crisis, disaster, betrayal, or narrow escape
- A SYSTEMIC LIE or MYTH-BUST: "Why [widely believed thing] is completely wrong"
- A FORGOTTEN TURNING POINT: a moment that changed everything but nobody talks about

TOPIC SELECTION CRITERIA (each topic MUST score high on):
1. CURIOSITY GAP: Can the title alone create "I NEED to know" urgency?
2. VISUAL THUMBNAIL POTENTIAL: One concrete, striking image that reads at 160x90px
3. EMOTIONAL STAKES: Life/death, freedom/slavery, truth/lie, survival/extinction
4. NARRATIVE MOMENTUM: A clear beginning→middle→end with escalation
5. UNIQUENESS: Not a Wikipedia summary - a SPECIFIC untold angle

Each topic needs a clear, specific, named anchor (a person, role, place, or event) - not a vague
category like "Ancient Rome" or "Greek Mythology" on their own. Each topic should also imply one
concrete, visually striking single moment (a specific action, object, or expression) that could
carry a thumbnail on its own - not just an interesting fact with no clear image attached. Avoid
anything copyrighted or that would require paid licensing to depict. Call {EMIT_TOPICS} with the
result."""

    data = _call_gemini(prompt, EMIT_TOPICS, schema, config, max_output_tokens=500)
    return list(data["topics"])
