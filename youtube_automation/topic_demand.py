"""Topic demand from Wikipedia pageviews: free, no API key, and a decent proxy for 'do people look this up?'.

For each candidate topic we find the best-matching English Wikipedia article and take its average daily views
over the last 60 days. The topic picker uses it as a mild multiplier (0.6-1.0) so that, among otherwise equal
candidates, the one with real audience interest wins. Strictly best-effort: any error -> no signal, never a failure."""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
_UA = {"User-Agent": "YT-AUTO/1.0 (topic demand ranking; https://github.com/omixz/YT-AUTO)"}
_CACHE: Dict[str, Optional[float]] = {}
_STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "that", "this", "where", "when", "which", "who", "how", "why", "with", "for", "was", "were", "is", "his", "her", "their", "its"}


def query_for(topic: str) -> str:
    """A short search string from a long topic sentence: the first ~9 meaningful words."""
    words = [w for w in re.findall(r"[A-Za-z0-9'\-]+", topic) if w.lower() not in _STOP]
    return " ".join(words[:9])


def _get(url: str, timeout: float = 6.0):
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return json.load(r)


def fetch_avg_daily_views(topic: str, days: int = 60) -> Optional[float]:
    """Average daily views of the best-matching enwiki article, or None if unavailable."""
    if topic in _CACHE:
        return _CACHE[topic]
    value: Optional[float] = None
    try:
        q = urllib.parse.quote(query_for(topic))
        hits = _get(f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&srlimit=1&format=json")["query"]["search"]
        if hits:
            title = urllib.parse.quote(hits[0]["title"].replace(" ", "_"), safe="")
            end = dt.date.today() - dt.timedelta(days=1)
            start = end - dt.timedelta(days=days)
            items = _get("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
                         f"{title}/daily/{start:%Y%m%d}/{end:%Y%m%d}")["items"]
            if items:
                value = sum(i["views"] for i in items) / len(items)
    except Exception as exc:  # noqa: BLE001
        logger.info("demand lookup failed for %r: %s", topic[:50], exc)
    _CACHE[topic] = value
    return value


def demand_factors(topics: List[str], fetch=fetch_avg_daily_views) -> Dict[str, float]:
    """topic -> multiplier in [0.6, 1.0] (log-scaled vs the best candidate); neutral 0.8 when unknown.
    Returns all-1.0 if fewer than two candidates have data (no basis for comparison)."""
    raw = {t: fetch(t) for t in topics}
    known = {t: v for t, v in raw.items() if v is not None}
    if len(known) < 2:
        return {t: 1.0 for t in topics}
    top = math.log10(1 + max(known.values())) or 1.0
    return {t: (0.6 + 0.4 * math.log10(1 + known[t]) / top) if t in known else 0.8 for t in topics}
