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


# --------------------------------------------------------------------------------------------------
# Accurate casting. The old cast was random (30% female lead, any of 5 skin tones), and each scene
# picked a random member, so one story's lead changed gender/ethnicity between scenes. Now:
#   1. the script model names the real people (gender, skin, age, kind) and who is in each scene;
#   2. without that, one regional skin palette is used for the whole cast and the lead's gender
#      follows the narration's pronouns.
# --------------------------------------------------------------------------------------------------
SKIN_BY_NAME = {"light": 0, "olive": 1, "tan": 2, "brown": 3, "dark": 4}
_REGIONS = (   # (keywords, skin tone indices that fit the people of that region)
    (("japan", "japanese", "samurai", "china", "chinese", "korea", "korean", "mongol", "tokyo", "beijing", "shogun",
      "manchuria", "vietnam", "emperor hirohito"), (0, 1)),
    (("africa", "african", "zulu", "ethiopia", "mali", "congo", "nigeria", "kenya", "ghana", "sudan", "nubia",
      "kush", "timbuktu"), (3, 4)),
    (("india", "indian", "mughal", "bengal", "delhi", "persia", "persian", "arab", "baghdad", "ottoman", "egypt",
      "pharaoh", "cairo", "babylon", "mesopotamia", "aztec", "maya", "inca", "mexico", "peru", "sultan"), (1, 2, 3)),
    (("america", "american", "britain", "british", "england", "english", "france", "french", "germany", "german",
      "nazi", "russia", "russian", "soviet", "rome", "roman", "greece", "greek", "viking", "norse", "spain",
      "spanish", "italy", "italian", "poland", "austria", "habsburg", "europe", "london", "paris", "berlin",
      "scotland", "ireland", "sparta", "athens", "medieval", "knight", "tsar"), (0, 0, 1)),
)
_SHE = re.compile(r"\b(she|her|hers|herself|woman|girl|queen|princess|mother|wife|daughter|lady|widow|sister|empress)\b")
_HE = re.compile(r"\b(he|him|his|himself|man|boy|king|prince|father|husband|son|lord|brother|emperor)\b")
_PLURAL = re.compile(r"\b(they|them|both|together|two|three|crew|men|women|brothers|sisters|couple|family|"
                     r"partners|friends|soldiers|officers|guards|sailors|detectives|investigators|team|pair)\b")

PROP_ERAS = {  # props that only belong in some eras
    "rifle": {"early_modern", "victorian", "ww1", "interwar", "ww2", "modern"},
    "pistol": {"early_modern", "victorian", "ww1", "interwar", "ww2", "modern"},
    "telescope": {"early_modern", "victorian", "ww1", "interwar", "ww2", "modern"},
    "sword": {"ancient", "medieval", "early_modern", "victorian"}, "spear": {"ancient", "medieval"},
    "axe": {"ancient", "medieval", "early_modern"}, "shield": {"ancient", "medieval"},
    "scroll": {"ancient", "medieval", "early_modern"},
}
_PROP_WORDS = (   # narration keyword -> prop (first match wins)
    ("letter", ("letter", "telegram", "note ", "message", "wrote to", "ransom note")),
    ("map", ("map", "chart", "route", "coordinates")),
    ("book", ("book", "diary", "journal", "ledger", "manuscript", "bible", "notebook")),
    ("pistol", ("pistol", "revolver", "gunman", "shot him", "shot her", "handgun", "gunshot")),
    ("rifle", ("rifle", "musket", "sniper", "machine gun", "firing squad")),
    ("sword", ("sword", "blade", "duel")),
    ("torch", ("torch",)),
    ("lantern", ("lantern", "lamp", "candle")),
    ("telescope", ("telescope", "spyglass", "binocular", "lookout")),
    ("bag", ("gold", "coins", "ransom", "treasure", "money", "fortune")),
)


def region_tones(text: str) -> tuple:
    """Skin tone indices that fit where this story happens (most-mentioned region wins)."""
    t = text.lower()
    best, hits = (0, 1, 2), 0
    for words, tones in _REGIONS:
        n = sum(t.count(w) for w in words)
        if n > hits:
            best, hits = tones, n
    return best


def lead_is_female(text: str) -> bool:
    t = text.lower()
    she, he = len(_SHE.findall(t)), len(_HE.findall(t))
    return she >= 3 and she > he * 1.2


def scene_gender(text: str) -> "bool | None":
    """True/False when a scene's narration clearly talks about a woman / a man, else None."""
    t = text.lower()
    she, he = len(_SHE.findall(t)), len(_HE.findall(t))
    if she and not he:
        return True
    if he and not she:
        return False
    return None


def mentions_group(text: str) -> bool:
    return bool(_PLURAL.search(text.lower()))


def prop_for(text: str, era: str, said: str = "") -> "str | None":
    """The prop a scene should show: the script's choice if it fits the era, else a narration keyword, else None."""
    from .character import PROPS
    if said in PROPS and era in PROP_ERAS.get(said, {era}):
        return said
    t = text.lower() + " "
    for prop, words in _PROP_WORDS:
        if any(w in t for w in words) and era in PROP_ERAS.get(prop, {era}):
            return prop
    return None


def _default_prop(kind: str, era: str, rng: random.Random) -> "str | None":
    if kind in {"soldier", "officer"}:
        if era in {"ww1", "interwar", "ww2", "modern", "victorian"}:
            return "rifle" if kind == "soldier" else rng.choice(["pistol", "map", None])
        if era == "early_modern":
            return rng.choice(["rifle", "sword"])
        return rng.choice(["sword", "spear", "shield"])
    if kind == "scholar":
        return rng.choice(["book", "scroll" if era in {"ancient", "medieval"} else "book", "letter"])
    if kind == "sailor":
        return "telescope" if era in PROP_ERAS["telescope"] else None
    if kind == "royal":
        return "scroll" if era in {"ancient", "medieval"} else None
    return None


def look_from_spec(spec: dict, era: str, region: tuple, rng: random.Random) -> Look:
    """A Look that honours the script's description of a real person."""
    female = str(spec.get("gender", "")).lower().startswith("f")
    kind = str(spec.get("kind", "civilian")).lower()
    age = str(spec.get("age", "adult")).lower()
    military = kind in {"soldier", "officer"}
    look = random_look(era, rng, military=military, female=female)
    tone = SKIN_BY_NAME.get(str(spec.get("skin", "")).lower())
    look.skin = SKIN_TONES[tone] if tone is not None else SKIN_TONES[rng.choice(region)]
    if tone is not None and tone >= 3 and look.hair in (HAIR_COLORS[-1], HAIR_COLORS[-2]):
        look.hair = HAIR_COLORS[0]
    if age == "old":
        look.hair, look.glasses = (214, 214, 218), rng.random() < 0.6
        if not female and look.hair_style == "curly":
            look.hair_style = "bald"
    else:
        if look.hair == (214, 214, 218):   # random_look made them old; this person is young/adult
            look.hair = rng.choice(HAIR_COLORS[:4] if (tone or 0) >= 3 else HAIR_COLORS)
            look.glasses = rng.random() < 0.1
            if look.hair_style == "bald" and age == "young":
                look.hair_style = "short"
        if age == "young":
            look.facial, look.glasses = "", False
            if look.hair_style == "bald":
                look.hair_style = "short"
            look.height *= 0.94
    if military and female:   # random_look only puts men in uniform; a named female soldier still wears one
        c = rng.choice(_UNIFORMS.get(era, ([(98, 104, 88)], []))[0])
        look.style, look.outfit, look.trousers = "uniform", c, tuple(int(v * 0.8) for v in c)
    if kind == "royal":
        look.headwear, look.style = "crown", ("dress" if female else "robe")
        look.outfit = rng.choice([(150, 40, 60), (90, 50, 140), (40, 70, 140)])
    elif kind in {"scholar", "priest"}:
        look.style = "robe" if era in {"ancient", "medieval"} or kind == "priest" else "coat"
        look.headwear = None
        look.outfit = (40, 40, 48) if kind == "priest" else look.outfit
    elif kind == "criminal":
        look.style, look.headwear, look.outfit = "coat", (rng.choice(["flatcap", None]) if era not in {"ancient", "medieval"} else None), (60, 60, 70)
    look.prop = _default_prop(kind, era, rng)
    return look


def build_cast_from_specs(specs: List[dict], era: str, text: str) -> List[Look]:
    import zlib
    region = region_tones(text)
    return [look_from_spec(s, era, region, random.Random(zlib.crc32(str(s.get("name", i)).lower().encode())))
            for i, s in enumerate(specs[:6])]


def build_regional_cast(era: str, rng: random.Random, military_share: float, text: str, n: int = 5) -> List[Look]:
    """Fallback cast when the script names nobody: consistent regional skin tones, lead gender from pronouns."""
    region = region_tones(text)
    female_lead = lead_is_female(text)
    cast = [random_look(era, rng, military=military_share > 0.5 and not female_lead, female=female_lead)]
    for i in range(n - 1):
        cast.append(random_look(era, rng, military=rng.random() < military_share, female=(i % 2 == 0)))
    for look in cast:
        look.skin = SKIN_TONES[rng.choice(region)]
        if look.skin in SKIN_TONES[3:] and look.hair in (HAIR_COLORS[-1], HAIR_COLORS[-2]):
            look.hair = HAIR_COLORS[0]
    return cast
