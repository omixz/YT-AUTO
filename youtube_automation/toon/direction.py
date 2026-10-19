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


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def direct(scenes, durations: List[float], title: str = "") -> List[SceneDirection]:
    from .. import procedural_illustration as P

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
        out.append(SceneDirection(index=i, setting=(directed_setting or hinted or settings[i]), archetype=archetype, rival=rival, mood=mood,
                                  action=action, camera=camera, tod=tod, role=role, seed=i, emotes=emotes,
                                  mascot=True))   # Pip is the narrator: present in every scene
    return out
