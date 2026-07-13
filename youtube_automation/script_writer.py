"""Generates a scene-by-scene video script for a topic, using Gemini function-
calling for guaranteed-structured output (no fragile JSON-in-prose parsing).

Uses the raw REST API via `requests` (already a project dependency) rather
than adding the google-genai SDK - the request/response shapes are simple
enough that a thin wrapper here is less to maintain than a full SDK.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

import requests

from .config import PipelineConfig

MODEL = "gemini-flash-latest"
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
                            "the script gets a chance. "
                            "build: 3+ middle scenes that develop connected facts into a mini-story "
                            "(use transitions like 'but here's the twist' / 'and that's not even "
                            "the strangest part' - don't just list isolated trivia). "
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

# Transient 503 "model overloaded" responses are common and worth one retry
# rather than failing a whole scheduled run over it.
_RETRY_STATUSES = {503}
_MAX_RETRIES = 2


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
        # thinkingBudget=0: this task needs direct structured generation, not
        # extended reasoning, and leaving thinking on ate a large fraction of
        # max_output_tokens on "thoughts" rather than the actual script.
        "generationConfig": {"maxOutputTokens": max_output_tokens, "thinkingConfig": {"thinkingBudget": 0}},
    }

    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        response = requests.post(
            API_URL,
            params={"key": config.secrets.gemini_api_key},
            json=body,
            timeout=120,
        )
        if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            last_error = response.text
            time.sleep(2 ** attempt)
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


def generate_script(topic: str, config: PipelineConfig) -> Script:
    """Ask Gemini to write a full scene-by-scene script for one video."""
    # ~140 spoken words per minute is a safe average for narration pacing.
    target_words = max(60, round(config.video.target_seconds * 140 / 60))
    # ~25 words per scene keeps each one a genuine "1-2 sentences a few seconds
    # long" beat rather than a paragraph - matters a lot once target_words
    # gets into longform territory (a fixed "6-9 scenes" would otherwise force
    # multi-sentence walls of narration per scene, or the model quietly
    # ignoring the length target to keep scenes short).
    suggested_scenes = max(6, min(60, round(target_words / 25)))
    max_output_tokens = min(8000, max(2000, round(target_words * 4) + 500))

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

Write a script of roughly {target_words} words of total narration ({config.video.target_seconds}
seconds at a natural speaking pace), split into roughly {suggested_scenes} short scenes with
this shape:
- One "hook" scene (first): a surprising claim or question that earns the runtime that follows.
- {suggested_scenes - 2}+ "build" scenes: connected facts that develop one throughline, not a
  random list - use connective tissue ("but here's the twist...", "which raises the
  question...", "and that's the part most people get wrong...").
- One "insight" scene (last): a real "why this matters" synthesis that ties the throughline
  together - genuine analysis, not just one more fact.

Each scene's narration should be 1-2 sentences a voice actor can read in a few seconds - do not
write paragraph-length narration for a single scene, split it into more scenes instead. Give
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
Each topic needs a clear, specific, named anchor (a person, role, place, or event) - not a vague
category like "Ancient Rome" or "Greek Mythology" on their own. Avoid anything copyrighted or that
would require paid licensing to depict. Call {EMIT_TOPICS} with the result."""

    data = _call_gemini(prompt, EMIT_TOPICS, schema, config, max_output_tokens=500)
    return list(data["topics"])
