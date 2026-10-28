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
VALID_SETTINGS = ['ancient', 'battlefield', 'city', 'courtroom', 'default', 'desert', 'dungeon', 'forest', 'government', 'harbor', 'indoor', 'island', 'mountain', 'mythic', 'palace', 'ruins', 'shipdeck', 'snow', 'warroom', 'water']
VALID_ACTIONS = {"talk", "walk", "fight", "crowd", "shock"}
_SETTING_HINTS = (  # fallback only, for scenes the model did not direct; checked before the legacy resolver
    ("battlefield", ("trench", "battlefield", "no man's land", "frontline", "front line", "shelling", "bombardment", "artillery", "offensive", "stormed")),
    ("warroom", ("headquarters", "general staff", "war room", "map table", "command post", "briefing", "war council", "supreme command")),
    ("shipdeck", ("cruise", "ocean liner", "aboard", "passenger", "on deck", "ship's deck", "stateroom")),
    ("island", ("island", "beach", "castaway", "shipwreck", "shoreline")),
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
    cta: str = ""                      # "" | "mid" (reminder card for ~3.4s) | "final" (stays to the end)
    callouts: List[Tuple[float, str]] = field(default_factory=list)   # (time_in_scene, label) number/date cards


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def direct(scenes, durations: List[float], title: str = "") -> List[SceneDirection]:
    import zlib
    from .. import procedural_illustration as P
    from . import casting
    from .character import Look

    era = casting.detect_era(scenes, title)
    mil_share = sum(casting.is_military(sc.narration) for sc in scenes) / max(1, len(scenes))
    crng = random.Random(zlib.crc32((title or scenes[0].narration).encode()))
    cast = casting.build_cast(era, crng, mil_share)
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
        # --- who is on screen: a recurring cast member (protagonist most often), never the same twice in a row
        hero_idx = 0 if rng.random() < 0.38 else rng.randrange(len(cast))
        if hero_idx == last_hero:
            hero_idx = (hero_idx + 1) % len(cast)
        last_hero = hero_idx
        hero = cast[hero_idx]
        themed = next((w for w in _THEMED if w in text), "")
        if themed and era in {"ancient", "medieval"}:
            hero = Look.from_archetype(P._resolve_character_archetype(scene), P._CHARACTER_ARCHETYPES, rng)
        rival_look = casting.random_look(era, random.Random(2000 + i), military=True, female=False)
        shot = "close" if (role == "hook" or mood == "shocked") else "wide" if action == "walk" else "medium" if action in {"fight", "crowd"} else ["medium", "wide", "medium", "close"][i % 4]
        out.append(SceneDirection(index=i, setting=(directed_setting or hinted or settings[i]), archetype=archetype, rival=rival, mood=mood,
                                  action=action, camera=camera, tod=tod, role=role, seed=i, emotes=emotes,
                                  mascot=True, era=era, shot=shot, hero=hero, rival_look=rival_look))   # Pip is the narrator: present in every scene
    # Like/subscribe reminders: Shorts get one at the very end; longform one ~40% in (after the hook has paid off) and one at the end.
    if out:
        out[-1].cta = "final"
        if len(out) >= 8:
            out[int(len(out) * 0.4)].cta = "mid"
    return out
