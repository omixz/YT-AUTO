"""Generates a scene-by-scene video script for a topic, using Claude tool-use
for guaranteed-structured output (no fragile JSON-in-prose parsing)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import anthropic

from .config import PipelineConfig

MODEL = "claude-sonnet-5"

SCRIPT_TOOL = {
    "name": "emit_script",
    "description": "Return the finished short-form video script.",
    "input_schema": {
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
    },
}

TOPICS_TOOL_NAME = "emit_topics"


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


def _client(config: PipelineConfig) -> anthropic.Anthropic:
    if not config.secrets.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to youtube-automation/.env "
            "(copy .env.example first)."
        )
    return anthropic.Anthropic(api_key=config.secrets.anthropic_api_key)


def generate_script(topic: str, config: PipelineConfig) -> Script:
    """Ask Claude to write a full scene-by-scene script for one video."""
    client = _client(config)

    # ~140 spoken words per minute is a safe average for narration pacing.
    target_words = max(60, round(config.video.target_seconds * 140 / 60))
    # ~25 words per scene keeps each one a genuine "1-2 sentences a few seconds
    # long" beat rather than a paragraph - matters a lot once target_words
    # gets into longform territory (a fixed "6-9 scenes" would otherwise force
    # multi-sentence walls of narration per scene, or the model quietly
    # ignoring the length target to keep scenes short).
    suggested_scenes = max(6, min(60, round(target_words / 25)))
    max_tokens = min(8000, max(2000, round(target_words * 4) + 500))

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
each scene visual_keywords that a stock-footage search engine could use to find matching
{config.visuals.orientation}-orientation footage — concrete, filmable nouns, not abstract ideas.
Do not use markdown in the narration. Only state facts you're confident are accurate; do not
fabricate statistics or quotes. Call emit_script with the final result."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        tools=[SCRIPT_TOOL],
        tool_choice={"type": "tool", "name": "emit_script"},
        messages=[{"role": "user", "content": prompt}],
    )

    data = next(block.input for block in response.content if block.type == "tool_use")

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
    """Ask Claude for fresh topic ideas that avoid what's already been made."""
    client = _client(config)

    tool = {
        "name": TOPICS_TOOL_NAME,
        "description": "Return a list of fresh video topic ideas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topics"],
        },
    }

    used_list = "\n".join(f"- {t}" for t in existing) or "(none yet)"
    prompt = f"""Channel niche: {config.channel.niche}
Audience: {config.channel.audience}

Already-used topics (do not repeat these or close variants):
{used_list}

Suggest {count} new, specific, high-interest video topics for this channel. Avoid anything
copyrighted or that would require paid licensing to depict. Call {TOPICS_TOOL_NAME} with the result."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        tools=[tool],
        tool_choice={"type": "tool", "name": TOPICS_TOOL_NAME},
        messages=[{"role": "user", "content": prompt}],
    )

    data = next(block.input for block in response.content if block.type == "tool_use")
    return list(data["topics"])
