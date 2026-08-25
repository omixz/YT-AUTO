"""Builds burn-in captions for the whole video from per-scene word cues.

Produces an ASS (Advanced SubStation Alpha) file with karaoke (\\k) timing
tags rather than a plain SRT: libass reveals each word in the accent colour
exactly as edge-tts's real word-boundary timestamps say it's spoken, so the
caption highlights track the voiceover word-by-word instead of just fading
a static line of text in and out.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .tts import SceneAudio

WORDS_PER_CAPTION = 4

# Bold white base text; the accent colour "fills in" each word as it's
# spoken (ASS \k karaoke: SecondaryColour is the not-yet-spoken colour,
# PrimaryColour is what it becomes once its timer elapses).
FONT_NAME = "Outfit"
BASE_COLOUR = "&H00FFFFFF"     # white (not yet spoken)
HIGHLIGHT_COLOUR = "&H0046D4FE"  # warm gold-yellow (ASS is &HAABBGGRR -> this is #FED446)
OUTLINE_COLOUR = "&H00000000"  # black outline

# --- on-screen emphasis "pop" cards ----------------------------------------
EMPHASIS_TEXT_COLOUR = "&H00161616"   # near-black, for contrast against the gold chip
EMPHASIS_BOX_COLOUR = HIGHLIGHT_COLOUR
EMPHASIS_MAX_SECONDS = 2.2
EMPHASIS_MIN_SCENE_SECONDS = 0.6


def _emphasis_style_line(font_size: int, margin_v: int) -> str:
    return (
        f"Style: Emphasis,{FONT_NAME},{font_size},{EMPHASIS_TEXT_COLOUR},{EMPHASIS_TEXT_COLOUR},"
        f"{EMPHASIS_BOX_COLOUR},{EMPHASIS_BOX_COLOUR},1,0,0,0,100,100,0,0,3,18,0,8,60,60,{margin_v},1"
    )


def _ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = round(seconds * 100)
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "").replace("}", "")


def build_ass(
    scenes: List[SceneAudio],
    out_path: Path,
    resolution: Tuple[int, int],
    on_screen_texts: Optional[List[str]] = None,
) -> Path:
    """`on_screen_texts`, if given, must be the same length as `scenes` (one
    entry per scene, empty string for "none") - each non-empty entry pops in
    as a bold emphasis chip near the top of frame for the start of that
    scene. Optional and length-checked rather than required so existing
    callers/tests that only care about karaoke captions keep working
    untouched."""
    if on_screen_texts is not None and len(on_screen_texts) != len(scenes):
        raise ValueError(
            f"on_screen_texts length ({len(on_screen_texts)}) must match scenes length ({len(scenes)})"
        )

    w, h = resolution
    # Scales with resolution so shorts (portrait, narrower) and longform
    # (landscape) both read comfortably; noticeably bigger than the old
    # fixed FontSize=16.
    font_size = round(h * 0.052)
    margin_v = round(h * 0.09)
    emphasis_font_size = round(h * 0.062)
    emphasis_margin_v = round(h * 0.06)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{font_size},{HIGHLIGHT_COLOUR},{BASE_COLOUR},{OUTLINE_COLOUR},&H00000000,1,0,0,0,100,100,0,0,1,3,0,2,60,60,{margin_v},1
{_emphasis_style_line(emphasis_font_size, emphasis_margin_v)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    offset = 0.0
    for scene_idx, scene in enumerate(scenes):
        if on_screen_texts is not None:
            text = (on_screen_texts[scene_idx] or "").strip()
            if text and scene.duration >= EMPHASIS_MIN_SCENE_SECONDS:
                show_for = min(EMPHASIS_MAX_SECONDS, scene.duration * 0.7)
                start = offset
                end = offset + show_for
                fade_ms = max(80, min(180, int(show_for * 400)))
                pop_ms = max(80, min(160, int(show_for * 300)))
                override = (
                    f"{{\\an8\\fad({fade_ms},{fade_ms})"
                    f"\\fscx55\\fscy55\\t(0,{pop_ms},\\fscx108\\fscy108)"
                    f"\\t({pop_ms},{pop_ms + 80},\\fscx100\\fscy100)}}"
                )
                emphasis_text = _escape(text).upper()
                lines.append(
                    f"Dialogue: 1,{_ass_timestamp(start)},{_ass_timestamp(end)},Emphasis,,0,0,0,,{override}{emphasis_text}"
                )

        cues = scene.cues
        for i in range(0, len(cues), WORDS_PER_CAPTION):
            group = cues[i : i + WORDS_PER_CAPTION]
            if not group:
                continue
            start = offset + min(group[0].start, scene.duration)
            end = offset + min(group[-1].end, scene.duration)
            if end <= start:
                continue

            karaoke_text = ""
            prev_end = group[0].start
            for cue in group:
                # Duration this word is "active" for, in centiseconds - clamp
                # to >=1 so a zero-length cue (rare, but real TTS timing can
                # be noisy) never produces a malformed \k0 tag.
                gap = max(0, round((cue.start - prev_end) * 100))
                dur = max(1, round((cue.end - cue.start) * 100))
                if gap:
                    karaoke_text += f"{{\\k{gap}}}"
                # \kf (not \k): sweeps the highlight across the word over its
                # own spoken duration, so the fill tracks *while* the word is
                # being said rather than snapping to highlighted only once
                # it's already finished.
                karaoke_text += f"{{\\kf{dur}}}{_escape(cue.text)} "
                prev_end = cue.end

            lines.append(
                f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,{karaoke_text.strip()}"
            )
        offset += scene.duration

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# --- SRT (kept for anything that still wants plain, non-karaoke captions) --

def _srt_timestamp(seconds: float) -> str:
    total_ms = int(max(0.0, seconds) * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(scenes: List[SceneAudio], out_path: Path) -> Path:
    lines = []
    offset = 0.0
    index = 1

    for scene in scenes:
        cues = scene.cues
        for i in range(0, len(cues), WORDS_PER_CAPTION):
            group = cues[i : i + WORDS_PER_CAPTION]
            if not group:
                continue
            start = offset + min(group[0].start, scene.duration)
            end = offset + min(group[-1].end, scene.duration)
            text = " ".join(c.text for c in group)
            lines.append(str(index))
            lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
            lines.append(text)
            lines.append("")
            index += 1
        offset += scene.duration

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
