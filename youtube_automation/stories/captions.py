"""Word-timed, pop-in captions (ASS subtitles burned in by ffmpeg/libass) for story Shorts."""
from __future__ import annotations

from typing import List, Tuple

Word = Tuple[float, float, str]   # (start_s, end_s, text)

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Outfit,112,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,9,4,5,60,60,0,1
Style: Title,Outfit,84,&H00141414,&H00141414,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,26,0,8,80,80,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HIGHLIGHT = r"{\c&H2EE6FF&}"     # yellow (ASS colours are BGR)
WHITE = r"{\c&HFFFFFF&}"


def _ts(s: float) -> str:
    s = max(0.0, s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(words: List[Word], max_words: int = 3, max_chars: int = 16) -> List[List[Word]]:
    """Short groups (1-3 words) that break at punctuation - the fast, punchy style story Shorts use."""
    groups: List[List[Word]] = []
    cur: List[Word] = []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x[2] for x in cur + [w])) > max_chars):
            groups.append(cur)
            cur = []
        cur.append(w)
        if w[2][-1:] in ".!?,;:":
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: List[Word], title: str, title_secs: float = 2.6, y: int = 1150) -> str:
    lines = [HEADER]
    if title:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(title_secs)},Title,,0,0,0,,{{\\fad(0,250)}}{_esc(title)}")
    events = []   # (start, text) - one per spoken word; each lasts until the next one starts, so two never overlap
    for g in group_words(words):
        for k, (start, _end, _t) in enumerate(g):
            text = " ".join((HIGHLIGHT if j == k else WHITE) + _esc(x[2]) for j, x in enumerate(g))
            pop = r"{\fscx80\fscy80\t(0,90,\fscx100\fscy100)}" if k == 0 else ""
            events.append((start, pop + text))
    final_end = words[-1][1] + 0.4 if words else 0.0
    for i, (start, text) in enumerate(events):
        end = events[i + 1][0] if i + 1 < len(events) else final_end
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(max(end, start + 0.04))},Cap,,0,0,0,,{{\\pos(540,{y})}}{text}")
    return "\n".join(lines) + "\n"
