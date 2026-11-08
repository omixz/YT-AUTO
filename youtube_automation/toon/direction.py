"""Scene -> directing decisions (setting, cast, action, camera, emotes).

Today this is derived from the keywords/role the script already has, reusing the
legacy renderer's lookup tables so both engines agree on 'what is this scene
about'. Later the LLM can fill a richer `direction` block and override this."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_NIGHT = ("night", "midnight", "dark ", "darkness", "moon", "shadow", "secret", "murder", "ghost", "haunted")
_DUSK = ("dusk", "sunset", "dawn", "twilight", "evening", "sunrise")
_WALK = ("march", "walked", "walk ", "journey", "travel", "fled", "escape", "sailed", "voyage", "expedition",
         "trek", "wandered", "searched", "pursued", "headed", "set out", "set off")
_QUESTION = ("?", "mystery", "mysterious", "unknown", "unexplained", "strange", "why ", "how did", "nobody knows", "no one knows", "puzzle", "vanish", "disappear")
_FEAR = ("fear", "afraid", "terror", "horrif", "panic", "dread", "scream", "flee", "danger", "trap", "doomed", "ambush")
_JOY = ("treasure", "gold", "discover", "triumph", "victory", "glory", "won ", "celebrat", "crowned", "found ")
VALID_SETTINGS = ['ancient', 'battlefield', 'camp', 'church', 'city', 'courtroom', 'default', 'desert', 'dungeon', 'forest', 'government',
                  'harbor', 'indoor', 'island', 'jungle', 'library', 'mountain', 'mythic', 'palace', 'ruins', 'shipdeck', 'snow',
                  'street', 'tavern', 'village', 'warroom', 'water']
VALID_ACTIONS = {"talk", "walk", "fight", "crowd", "shock"}
_SETTING_HINTS = (  # fallback only, for scenes the model did not direct; checked before the legacy resolver
    ("battlefield", ("trench", "battlefield", "no man's land", "frontline", "front line", "shelling", "bombardment", "artillery", "offensive", "stormed")),
    ("warroom", ("headquarters", "general staff", "war room", "map table", "command post", "briefing", "war council", "supreme command")),
    ("shipdeck", ("cruise", "ocean liner", "aboard", "passenger", "on deck", "ship's deck", "stateroom")),
    ("island", ("island", "beach", "castaway", "shipwreck", "shoreline")),
    ("library", ("library", "archive", "manuscript", "scholar", "study ", "university")),
    ("church", ("church", "cathedral", "monastery", "chapel", "monk", "abbey", "mass ")),
    ("tavern", ("tavern", " inn ", " pub ", "saloon", "alehouse")),
    ("jungle", ("jungle", "rainforest", "amazon")),
    ("camp", ("camp ", "encampment", "tents", "base camp", "bivouac")),
    ("village", ("village", "peasant", "farmhouse", "hamlet", "market square")),
    ("street", ("street", "alley", "sidewalk", "avenue")),
)
_RIVALS = ["pirate", "knight", "viking", "samurai", "gladiator", "general", "assassin", "roman"]


@dataclass
class SceneDirection:
    index: int
    setting: str
    archetype: str
    rival: str
    mood: str                       # neutral | shocked | serious
    action: str                     # talk | walk | fight | crowd
    camera: str                     # push_in | pull_out | pan_left | pan_right
    tod: str                        # day | dusk | night
    role: str
    seed: int
    emotes: List[Tuple[float, str]] = field(default_factory=list)
    mascot: bool = False
    era: str = "modern"
    shot: str = "medium"                 # wide | medium | close
    hero: Optional[object] = None        # toon.character.Look for the on-screen character
    rival_look: Optional[object] = None
    companions: List[object] = field(default_factory=list)   # other cast members on screen with the hero (0-2)
    cta: str = ""                      # "" | "early" (pop-up reminder ~3.4s, in the first 10-20s) | "final" (stays to the end)
    cta_t: float = 0.6                 # seconds into the scene when the card appears
    callouts: List[Tuple[float, str]] = field(default_factory=list)   # (time_in_scene, label) number/date cards


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def _cast_index(names, wanted: str) -> int:
    w = (wanted or "").strip().lower()
    if not w:
        return -1
    for i, n in enumerate(names):
        if n == w or (w in n or n in w) and min(len(n), len(w)) >= 3:
            return i
    return -1


def direct(scenes, durations: List[float], title: str = "", characters: Optional[list] = None) -> List[SceneDirection]:
    import zlib
    from .. import procedural_illustration as P
    from . import casting
    from .character import Look

    era = casting.detect_era(scenes, title)
    mil_share = sum(casting.is_military(sc.narration) for sc in scenes) / max(1, len(scenes))
    crng = random.Random(zlib.crc32((title or scenes[0].narration).encode()))
    story = title + " " + " ".join(sc.narration for sc in scenes)
    specs = [c for c in (characters or []) if isinstance(c, dict) and c.get("name")]
    if specs:   # the script named the real people: their gender/skin/age/role are honoured exactly
        cast = casting.build_cast_from_specs(specs, era, story)
    else:       # one regional skin palette for everyone; the lead's gender follows the narration's pronouns
        cast = casting.build_regional_cast(era, crng, mil_share, story)
    names = [str(c.get("name", "")).strip().lower() for c in specs]
    last_hero = -1
    _THEMED = ("pharaoh", "viking", "pirate", "samurai", "gladiator", "caesar", "knight")
    settings = P._resolve_settings_for_video(scenes)
    out: List[SceneDirection] = []
    prev_camera = ""
    for i, scene in enumerate(scenes):
        text = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower() + " "
        rng = random.Random(1000 + i)
        archetype = P._resolve_character_archetype(scene)
        directed_setting = getattr(scene, "setting", "") if getattr(scene, "setting", "") in VALID_SETTINGS else ""
        hinted = next((k for k, words in _SETTING_HINTS if _has(text, words)), "")
        rival = rng.choice([r for r in _RIVALS if r != archetype])
        shocked = (P._match(scene, P._KEYWORD_TO_MOOD) == "shocked") if hasattr(P, "_match") else False
        walk = _has(text, _WALK)
        said = getattr(scene, "action", "")
        # The model's direction wins. Without it, never guess fight/crowd from keywords - ordinary war
        # vocabulary ("fought", "soldiers", "clash") made every scene a brawl. Fallback = talk or walk.
        action = said if said in VALID_ACTIONS else ("walk" if walk else "talk")
        if action in {"fight", "crowd"} and out and out[-1].action in {"fight", "crowd"}:
            action = "talk"   # never two busy scenes in a row
        said_mood = getattr(scene, "mood", "")
        mood = said_mood if said_mood in {"neutral", "serious", "shocked"} else (
            "serious" if (action == "fight" or _has(text, _FEAR)) else "shocked" if shocked else "neutral")
        said_tod = getattr(scene, "time_of_day", "")
        tod = said_tod if said_tod in {"day", "dusk", "night"} else (
            "night" if _has(text, _NIGHT) else "dusk" if _has(text, _DUSK) else "day")
        role = getattr(scene, "role", "build")
        camera = {"hook": "push_in", "insight": "pull_out"}.get(role)
        if camera is None:
            camera = "pan_right" if prev_camera != "pan_right" else "pan_left"
        prev_camera = camera
        emotes: List[Tuple[float, str]] = []
        if shocked:
            emotes.append((0.25, "!"))
        if _has(text, _QUESTION):
            emotes.append((1.1 if not shocked else 2.3, "?"))
        fight = action == "fight"
        if _has(text, _FEAR) and not fight:
            emotes.append((0.9, "sweat"))
        if fight:
            emotes.append((0.8, "anger"))
        if _has(text, _JOY):
            emotes.append((0.9, "sparkle"))
        if role == "insight":
            emotes.append((min(1.2, durations[i] * 0.3), "bulb"))
        # --- who is on screen
        from dataclasses import replace as _replace
        said_on = [n for n in (getattr(scene, "on_screen", None) or []) if isinstance(n, str)]
        picked = [k for k in (_cast_index(names, n) for n in said_on) if k >= 0]
        picked = list(dict.fromkeys(picked))
        if picked:                       # the script said exactly who is in this scene
            hero_idx = picked[0]
        else:                            # fallback: the protagonist most often, and never the wrong gender for the scene
            want_f = casting.scene_gender(scene.narration)
            pool = [k for k, c in enumerate(cast) if want_f is None or c.female == want_f] or list(range(len(cast)))
            hero_idx = 0 if (0 in pool and rng.random() < 0.55) else rng.choice(pool)
            if hero_idx == last_hero and len(pool) > 1:
                hero_idx = pool[(pool.index(hero_idx) + 1) % len(pool)]
        last_hero = hero_idx
        hero = cast[hero_idx]
        themed = next((w for w in _THEMED if w in text), "")
        if themed and era in {"ancient", "medieval"} and not specs:
            # themed costume, but the SAME person: keep skin, gender and hair (this used to re-roll the skin tone)
            costume = Look.from_archetype(P._resolve_character_archetype(scene), P._CHARACTER_ARCHETYPES, rng)
            hero = _replace(costume, skin=hero.skin, hair=hero.hair, female=hero.female, hair_style=hero.hair_style,
                            build=hero.build, height=hero.height, facial="" if hero.female else costume.facial,
                            beard=costume.beard and not hero.female)
        prop = casting.prop_for(scene.narration + " " + " ".join(scene.visual_keywords), era, getattr(scene, "prop", "") or "")
        if prop:
            hero = _replace(hero, prop=prop)
        # companions: who else is in the shot (none in fights/crowds, which already have their own extra people)
        companions = []
        if action not in {"fight", "crowd"}:
            if picked:
                companions = [cast[k] for k in picked[1:3]]
            elif casting.mentions_group(scene.narration) or rng.random() < 0.3:
                others = [k for k in range(len(cast)) if k != hero_idx]
                companions = [cast[k] for k in rng.sample(others, min(len(others), 2 if casting.mentions_group(scene.narration) else 1))]
        rival_look = casting.random_look(era, random.Random(2000 + i), military=True, female=False)
        rival_look.skin = cast[-1].skin   # same people as the story, never a random skin tone
        shot = "close" if (role == "hook" or mood == "shocked") else "wide" if action == "walk" else "medium" if action in {"fight", "crowd"} else ["medium", "wide", "medium", "close"][i % 4]
        out.append(SceneDirection(index=i, setting=(directed_setting or hinted or settings[i]), archetype=archetype, rival=rival, mood=mood,
                                  action=action, camera=camera, tod=tod, role=role, seed=i, emotes=emotes,
                                  mascot=True, era=era, shot=shot, hero=hero, rival_look=rival_look,
                                  companions=companions if shot != "close" else []))   # Pip is the narrator: present in every scene
    # Like/subscribe reminders: an early pop-up (viewers decide to subscribe in the first seconds - longform at ~12s,
    # Shorts at ~8s, always inside the first 10-20s window for longform) plus one that stays to the end.
    if out:
        total = sum(durations)
        target = 8.0 if total <= 75 else 12.0      # <=75s of content = a Short
        start = 0.0
        for i, dur in enumerate(durations):
            if start + dur > target and i < len(out) - 1:      # the scene that is on screen at `target`
                out[i].cta = "early"
                out[i].cta_t = min(max(0.4, target - start), max(0.4, dur - 3.6))
                break
            start += dur
        out[-1].cta = "final"
    return out
