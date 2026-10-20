"""Era-aware casting: who is on screen and what they wear.

The old renderer picked one of ~15 fantasy archetypes by keyword, so a 1914 war
story and a medieval one both got helmeted 'knights'. Here the video's era is
detected once (years in the text, then keywords), a small recurring CAST is built
for the video with varied bodies, ages, genders, skin tones, hair and clothing that
fit the era, and each scene picks one cast member."""
from __future__ import annotations

import random
import re
import statistics
from typing import List, Optional

from .character import HAIR_COLORS, SKIN_TONES, Look

_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9]|[1-9][0-9]{2})\b")
_MILITARY = ("soldier", "army", "troops", "battle", "war ", "trench", "regiment", "general", "officer", "commander",
             "infantry", "offensive", "frontline", "front line", "artillery", "marched", "invasion", "garrison")

_UNIFORMS = {  # era -> (uniform colours, helmets/hats worn with them)
    "ww1": ([(104, 124, 158), (122, 112, 84), (96, 100, 92)], ["adrian", "brodie", "pickelhaube", "kepi", "peaked"]),
    "ww2": ([(98, 104, 88), (122, 112, 84), (86, 92, 90)], ["stahlhelm", "brodie", "peaked", "beret"]),
}
_CIVIL_COLORS = [(176, 84, 72), (72, 112, 164), (92, 140, 96), (206, 164, 76), (130, 90, 150), (86, 86, 98), (196, 120, 70), (60, 120, 124)]
_EARTH = [(168, 132, 92), (200, 170, 120), (140, 100, 70), (176, 70, 60), (90, 120, 150), (220, 210, 190)]


def detect_era(scenes, title: str = "") -> str:
    text = (title + " " + " ".join(s.narration for s in scenes)).lower()
    if any(k in text for k in ("world war ii", "second world war", "wwii", "nazi", "1940s")):
        return "ww2"
    if any(k in text for k in ("world war i", "great war", "wwi", "western front", "charleroi", "somme", "verdun")):
        return "ww1"
    years = [int(m) for m in _YEAR.findall(text) if 100 <= int(m) <= 2029]
    if years:
        y = statistics.median(years)
        return ("ancient" if y < 500 else "medieval" if y < 1500 else "early_modern" if y < 1800 else "victorian" if y < 1914
                else "ww1" if y < 1919 else "interwar" if y < 1939 else "ww2" if y < 1946 else "modern")
    if any(k in text for k in ("pharaoh", "egypt", "roman", "greek", "myth", "caesar", "viking")):
        return "ancient"
    if any(k in text for k in ("king", "queen", "castle", "knight", "crusade")):
        return "medieval"
    return "modern"


def is_military(text: str) -> bool:
    t = text.lower() + " "
    return any(k in t for k in _MILITARY)


def random_look(era: str, rng: random.Random, military: bool = False, female: Optional[bool] = None) -> Look:
    female = rng.random() < 0.42 if female is None else female
    # people who read as old (white hair, glasses) vs young, short vs tall, slim vs stocky
    old = rng.random() < 0.22
    hair = (214, 214, 218) if old else rng.choice(HAIR_COLORS)
    look = Look(skin=rng.choice(SKIN_TONES), hair=hair, female=female,
                build=rng.uniform(0.84, 1.0) if female else rng.uniform(0.92, 1.24),
                height=rng.uniform(0.94, 1.04) if female else rng.uniform(0.98, 1.1),
                hair_style=rng.choice(["long", "long", "bun", "curly", "short"]) if female else
                           rng.choice(["short", "short", "short", "curly", "bald"] if not old else ["bald", "short"]),
                glasses=old and rng.random() < 0.6 or rng.random() < 0.1,
                facial="" if female else rng.choice(["", "", "mustache", "goatee", "beard"]))
    if era in _UNIFORMS and military and not female:
        colors, hats = _UNIFORMS[era]
        c = rng.choice(colors)
        look.style, look.outfit, look.trousers = "uniform", c, tuple(int(v * 0.8) for v in c)
        look.headwear = rng.choice(hats)
        look.facial = rng.choice(["mustache", "mustache", "", "goatee"])
        look.prop = rng.choice([None, None, "scroll", "compass"])
        return look
    col = rng.choice(_CIVIL_COLORS if era not in {"ancient", "medieval"} else _EARTH)
    look.outfit, look.trousers = col, tuple(int(v * 0.66) for v in col)
    if era == "ancient":
        look.style = "dress" if female else rng.choice(["robe", "shirt"])
        look.headwear = rng.choice([None, None, "turban", "crown"]) if not military else "helmet"
        look.hair_style = "long" if female else look.hair_style
        if military and not female:
            look.style, look.prop = "armor", rng.choice(["sword", "spear"])
            look.outfit = (176, 160, 110)
    elif era == "medieval":
        look.style = "dress" if female else rng.choice(["shirt", "robe", "coat"])
        look.headwear = None if female else rng.choice([None, None, "cap", "crown"])
        if military and not female:
            look.style, look.outfit, look.prop = "armor", (150, 156, 168), rng.choice(["sword", "axe", "spear"])
            look.headwear = "helmet"
    elif era in {"early_modern", "victorian"}:
        look.style = "dress" if female else "coat"
        look.headwear = rng.choice([None, "bun"][:1]) if female else rng.choice(["tricorn" if era == "early_modern" else "tophat", "flatcap", None])
        if military and not female:
            look.style, look.headwear, look.outfit = "uniform", "peaked", (60, 70, 120)
    elif era in {"ww1", "interwar", "ww2"}:
        look.style = "dress" if female else "coat"
        look.headwear = rng.choice([None, "beret", "flatcap"]) if not female else rng.choice([None, "beret"])
    else:  # modern
        look.style = rng.choice(["dress", "shirt"]) if female else rng.choice(["shirt", "shirt", "coat"])
        look.headwear = rng.choice([None, None, None, "flatcap"])
    if look.headwear == "bun":
        look.headwear = None
    return look


def build_cast(era: str, rng: random.Random, military_share: float, n: int = 5) -> List[Look]:
    """Protagonist first, then supporting characters; always a mix of men and women."""
    cast = [random_look(era, rng, military=military_share > 0.5, female=rng.random() < 0.3)]
    for i in range(n - 1):
        cast.append(random_look(era, rng, military=rng.random() < military_share, female=(i % 2 == 0)))
    return cast
