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
        "title": {"type": "string", "description": "YouTube title, under 100 chars, hook-forward."},
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
                            "hook: exactly the first scene, a surprising claim or question. "
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

    if config.video.format == "longform":
        visual_keyword_guidance = (
            "each scene visual_keywords as 2-4 concept words (e.g. 'mystery', 'data', 'clock', "
            "'location', 'idea') - these pick a simple icon from a small library, not a stock-"
            "footage search, so abstract themes are fine here, unlike for shorts"
        )
    else:
        visual_keyword_guidance = (
            "each scene visual_keywords that a stock-footage search engine could use to find "
            f"matching {config.visuals.orientation}-orientation footage — concrete, filmable "
            "nouns, not abstract ideas"
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

Suggest {count} new, specific, high-interest video topics for this channel. Avoid anything
copyrighted or that would require paid licensing to depict. Call {EMIT_TOPICS} with the result."""

    data = _call_gemini(prompt, EMIT_TOPICS, schema, config, max_output_tokens=500)
    return list(data["topics"])
