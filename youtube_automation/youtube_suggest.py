"""What people actually type into YouTube search: the autocomplete endpoint behind the search box. Free, no key.

Two uses: (1) a search phrase for the tags/description, so the video surfaces for it; (2) a 'search for X on YouTube'
call-to-action in TikTok captions - TikTok captions can't carry clickable links, so telling viewers the exact phrase to
search is the most reliable way to send them to the video. Best-effort: any failure returns None."""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger(__name__)
_STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "that", "this", "where", "when", "which", "who", "how", "why",
         "with", "for", "was", "were", "is", "his", "her", "their", "its", "by", "from", "as", "into", "after", "before"}


def _seeds(text: str) -> List[str]:
    # Years are dropped from the seed: people search "flannan isles lighthouse", not "1912 flannan isles lighthouse".
    words = [w for w in re.findall(r"[A-Za-z0-9'\-]+", text) if w.lower() not in _STOP and not re.fullmatch(r"(1[0-9]{3}|20[0-2][0-9])", w)]
    return [" ".join(words[:n]) for n in (4, 3, 2) if len(words) >= n]


def suggestions(query: str, timeout: float = 5.0) -> List[str]:
    url = "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=en&q=" + urllib.parse.quote(query)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return [s for s in data[1] if isinstance(s, str)]


def top_query(text: str, fetch=suggestions) -> Optional[str]:
    """The highest-ranked YouTube autocomplete suggestion that still clearly matches the topic
    (shares >=2 meaningful words with it), or None."""
    keys = {w.lower() for w in re.findall(r"[A-Za-z0-9'\-]+", text) if w.lower() not in _STOP}
    try:
        for seed in _seeds(text):
            for s in fetch(seed):
                if len(keys & {w.lower() for w in re.findall(r"[A-Za-z0-9'\-]+", s)}) >= 2 and 8 <= len(s) <= 60:
                    return s
    except Exception as exc:  # noqa: BLE001
        logger.info("YouTube suggest lookup failed: %s", exc)
    return None
