"""Generates a scene-by-scene video script for a topic, using Gemini function-
calling for guaranteed-structured output (no fragile JSON-in-prose parsing).

Uses the raw REST API via `requests` (already a project dependency) rather
than adding the google-genai SDK - the request/response shapes are simple
enough that a thin wrapper here is less to maintain than a full SDK.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Tuple

import requests

from .config import PipelineConfig

# Pinned to gemini-3.5-flash - a specific, stable, GA model id, NOT a
# rolling "-latest" alias (which silently hot-swaps to whatever release is
# current) and NOT gemini-2.5-flash (which turned out to already be
# deprecated: "no longer available to new users", a live 404 on a real
# scheduled run). Pinning to an explicit stable id means this can't get
# silently broken again by a future release swap; bump deliberately.
MODEL = "gemini-3.5-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "YouTube title, under 100 chars, hook-forward. Makes one specific, curiosity-gap promise (not a vague topic label) - the hook scene's opening line must deliver on exactly this promise, since a title/thumbnail that overpromises what the video actually opens with kills retention and the algorithm's willingness to keep distributing it."},
        "description": {"type": "string", "description": "YouTube description, 2-4 sentences plus hashtags."},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "8-15 relevant search tags."},
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
                },
                "required": ["role", "narration", "visual_keywords"],
            },
        },
    },
    "required": ["title", "description", "tags", "scenes"],
}

EMIT_SCRIPT = "emit_script"
EMIT_TOPICS = "emit_topics"

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
_MAX_RETRIES = 7
_MAX_BACKOFF_SECONDS = 60


@dataclass
class Scene:
    narration: str
    visual_keywords: List[str]
    role: str = "build"
    on_screen_text: str = ""


@dataclass
class Script:
    topic: str
    title: str
    description: str
    tags: List[str]
    scenes: List[Scene] = field(default_factory=list)

    @property
    def full_narration(self) -> str:
        return " ".join(scene.narration for scene in self.scenes)


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

    raise RuntimeError(f"Gemini did not call {function_name}: {data}")


def _script_length_params(target_seconds: int) -> Tuple[int, int, int]:
    """Returns (target_words, suggested_scenes, max_output_tokens) for a
    given target duration. Pulled out of generate_script so the actual
    numbers a given target_seconds produces are directly testable, without
    needing to mock the whole Gemini call chain."""
    # ~140 spoken words per minute is a safe average for narration pacing.
    target_words = max(60, round(target_seconds * 140 / 60))
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
    # gemini-3.5-flash's real ceiling is 65,536 output tokens (confirmed
    # against Google's published model card) - 8000 was never actually
    # close to that limit, it was just an unrelated conservative guess.
    suggested_scenes = max(6, min(160, round(target_words / 25)))
    max_output_tokens = min(32000, max(2000, round(target_words * 4) + 500))
    return target_words, suggested_scenes, max_output_tokens


def generate_script(topic: str, config: PipelineConfig) -> Script:
    """Ask Gemini to write a full scene-by-scene script for one video."""
    target_words, suggested_scenes, max_output_tokens = _script_length_params(config.video.target_seconds)

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

Write a script of roughly {target_words} words of total narration ({config.video.target_seconds}
seconds at a natural speaking pace), split into roughly {suggested_scenes} short scenes with
this shape:
- One "hook" scene (first): pattern interrupt + curiosity gap that earns the runtime.
- {suggested_scenes - 2}+ "build" scenes: connected facts, each opening a new loop before
  closing the last. Use connective tissue ("but here's the twist...", "which raises the
  question...", "and that's the part most people get wrong...").
- One "insight" scene (last): perspective shift that reframes the whole story.

Each scene's narration should target {config.video.target_scene_duration} seconds of speech 
({config.video.min_scene_duration}-{config.video.max_scene_duration} seconds acceptable) — 
do not write paragraph-length narration for a single scene, split it into more scenes instead. Give
{visual_keyword_guidance}.
Do not use markdown in the narration. Only state facts you're confident are accurate; do not
fabricate statistics or quotes. Call emit_script with the final result."""

    data = _call_gemini(prompt, EMIT_SCRIPT, SCRIPT_SCHEMA, config, max_output_tokens)

    scenes = [
        Scene(
            narration=s["narration"].strip(),
            visual_keywords=list(s["visual_keywords"]),
            role=s.get("role", "build"),
            on_screen_text=s.get("on_screen_text", "") or "",
        )
        for s in data["scenes"]
    ]

    return Script(
        topic=topic,
        title=data["title"].strip(),
        description=data["description"].strip(),
        tags=[t.strip() for t in data["tags"]],
        scenes=scenes,
    )


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
