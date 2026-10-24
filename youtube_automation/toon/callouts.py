"""Animated number/date callouts: a card that pops up exactly when the narrator says "1912" or
"5,000 men". Pure text analysis on the word cues the TTS already produced - free, no extra API calls."""
from __future__ import annotations

import re
from typing import List, Tuple

_YEAR = re.compile(r"^(1[0-9]{3}|20[0-2][0-9])$")
_BIG = re.compile(r"^\d{1,3}(,\d{3})+$|^\d{3,}$")
_UNITS = {"men", "soldiers", "troops", "people", "ships", "tons", "miles", "years", "days", "dead", "killed", "lives",
          "prisoners", "survivors", "casualties", "victims", "dollars", "pounds", "km", "kilometers", "feet", "hours",
          "weeks", "months", "sailors", "workers", "civilians", "horses", "tanks", "planes", "guns", "votes"}
MIN_GAP = 2.6          # seconds between callouts in one scene
HOLD = 2.3             # seconds a card stays on screen


def extract(cues, duration: float, max_per_scene: int = 2) -> List[Tuple[float, str]]:
    """[(start_time, label)] for years and big numbers (with their unit word) spoken in this scene."""
    out: List[Tuple[float, str]] = []
    words = [(c.text.strip(".,;:!?\"'()"), c.start) for c in cues]
    for i, (w, t) in enumerate(words):
        if t < 0.25 or t > duration - 0.9:
            continue
        label = None
        if _YEAR.match(w):
            label = w
        elif _BIG.match(w):
            nxt = words[i + 1][0].lower() if i + 1 < len(words) else ""
            label = f"{w} {nxt.upper()}" if nxt in _UNITS else w
        if label and (not out or t - out[-1][0] >= MIN_GAP):
            out.append((t, label))
        if len(out) >= max_per_scene:
            break
    return out
