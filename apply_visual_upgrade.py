import re

with open(r"C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\procedural_illustration.py", "r") as f:
    content = f.read()

# Replace the _compose_scene function header
old_func_start = '''def _compose_scene(rng, scene: Scene, config: PipelineConfig, subject: Optional[str]):
    """Draws the background (everything except the focal subject) onto a fresh
    image and returns (background, paint_subject, motion).

    - paint_subject(draw) renders the subject onto any draw context, so the
      same composition can be flattened into a still or drawn onto its own
      transparent layer for animation.
    - motion is (amp_x, amp_y, period_x, period_y): how the subject drifts,
      used by the animator. Aquatic subjects float in two axes; land subjects
      bob gently in place.
    """
    w, h = config.video.resolution
    base = Image.new("RGB", (w, h), SKY)
    draw = ImageDraw.Draw(base)
    base_scale = h / 1080

    if subject in _AQUATIC_SUBJECTS:'''

new_func = '''def _compose_scene(rng, scene: Scene, config: PipelineConfig, subject: Optional[str]):
    """Draws the background (everything except the focal subject) onto a fresh
    image and returns (background, paint_subject, motion, composition_info).

    - paint_subject(draw) renders the subject onto any draw context, so the
      same composition can be flattened into a still or drawn onto its own
      transparent layer for animation.
    - motion is (amp_x, amp_y, period_x, period_y): how the subject drifts,
      used by the animator. Aquatic subjects float in two axes; land subjects
      bob gently in place.
    - composition_info: dict with 'layout', 'camera_angle', 'subject_position'
      for downstream animation decisions (Ken Burns, sprite placement).
    """
    w, h = config.video.resolution
    base = Image.new("RGB", (w, h), SKY)
    draw = ImageDraw.Draw(base)
    base_scale = h / 1080

    # --- COMPOSITION VARIETY ---
    # Choose layout based on scene role + mood + randomness.
    # Hook: dramatic close-up or centered impact
    # Build: rule-of-thirds, off-center, environmental
    # Insight: wide, contemplative, pulled back
    # Fight/Crowd: wide to show action
    # Shocked: low angle (looking up) or tight
    mood = _match(scene, _KEYWORD_TO_MOOD) or "neutral"
    role = scene.role

    if role == "hook":
        layout = rng.choice(["centered_dramatic", "rule_of_thirds", "low_angle"])
    elif role == "insight":
        layout = rng.choice(["wide_environmental", "rule_of_thirds", "high_angle"])
    elif mood == "shocked" or _is_fight_scene(scene):
        layout = rng.choice(["wide_environmental", "low_angle", "rule_of_thirds"])
    elif _is_crowd_scene(scene):
        layout = rng.choice(["wide_environmental", "rule_of_thirds"])
    else:
        layout = rng.choice(["rule_of_thirds", "rule_of_thirds", "centered_natural", "wide_environmental"])

    composition_info = {"layout": layout, "camera_angle": "eye_level"}

    if subject in _AQUATIC_SUBJECTS:'''

if old_func_start in content:
    content = content.replace(old_func_start, new_func)
    print("Replaced function header")
else:
    print("Could not find old function header")

# Update aquatic return
old_aquatic_return = '''        motion = (26 * base_scale, 30 * base_scale, 7.0, 3.7)
        return base, paint, motion

    setting = _setting_for_scene(scene)'''

new_aquatic_return = '''        motion = (26 * base_scale, 30 * base_scale, 7.0, 3.7)
        return base, paint, motion, composition_info

    setting = _setting_for_scene(scene)'''

if old_aquatic_return in content:
    content = content.replace(old_aquatic_return, new_aquatic_return)
    print("Replaced aquatic return")

# Update subject drawers
old_subject_drawers = '''    if subject in _SUBJECT_DRAWERS:
        sd = _SUBJECT_DRAWERS[subject]

        def paint(d, phase=0.0):
            sd(d, rng, w * 0.5, ground_y - 180 * element_scale, element_scale, phase)
    elif _is_fight_scene(scene):'''

new_subject_drawers = '''    if subject in _SUBJECT_DRAWERS:
        sd = _SUBJECT_DRAWERS[subject]

        def paint(d, phase=0.0):
            # Subject position varies by layout
            if layout == "centered_dramatic":
                cx, cy = w * 0.5, ground_y - 180 * element_scale
                composition_info["camera_angle"] = "low"
            elif layout == "low_angle":
                cx, cy = w * 0.5, ground_y - 220 * element_scale
                composition_info["camera_angle"] = "low"
            elif layout == "rule_of_thirds":
                cx = rng.choice([w // 3, 2 * w // 3])
                cy = ground_y - 180 * element_scale
                composition_info["camera_angle"] = "eye_level"
            elif layout == "high_angle":
                cx, cy = w * 0.5, ground_y - 140 * element_scale
                composition_info["camera_angle"] = "high"
            else:  # wide_environmental
                cx = w * rng.uniform(0.2, 0.8)
                cy = ground_y - 180 * element_scale
                composition_info["camera_angle"] = "high"

            composition_info["subject_position"] = (cx, cy)
            sd(d, rng, cx, cy, element_scale, phase)
    elif _is_fight_scene(scene):'''

if old_subject_drawers in content:
    content = content.replace(old_subject_drawers, new_subject_drawers)
    print("Replaced subject drawers")

# Update fight scene
old_fight = '''            if max(punch_a, punch_b) > 0.9:
                _draw_impact_burst(d, (cx_a + cx_b) / 2, ground_y - 235 * fight_scale, fight_scale)
    else:
        outfit = _match(scene, _KEYWORD_TO_OUTFIT) or (150, 130, 110)'''

new_fight = '''            if max(punch_a, punch_b) > 0.9:
                _draw_impact_burst(d, (cx_a + cx_b) / 2, ground_y - 235 * fight_scale, fight_scale)
        composition_info["camera_angle"] = "eye_level"
        composition_info["subject_position"] = ((cx_a + cx_b) / 2, ground_y)
    else:
        outfit = _match(scene, _KEYWORD_TO_OUTFIT) or (150, 130, 110)'''

if old_fight in content:
    content = content.replace(old_fight, new_fight)
    print("Replaced fight scene")

# Update land character paint
old_land_paint = '''        def paint(d, phase=0.0):
            for x, color, idx, cscale in crowd_specs:
                _draw_background_person(d, rng, x, ground_y, cscale, color, phase, idx)
            draw_character(d, rng, w * 0.5, ground_y, character_scale, outfit, headwear, mood, pose, phase)

    motion = (0.0, 12 * base_scale, 0.0, 2.6)  # gentle in-place bob
    return base, paint, motion'''

new_land_paint = '''        def paint(d, phase=0.0):
            for x, color, idx, cscale in crowd_specs:
                _draw_background_person(d, rng, x, ground_y, cscale, color, phase, idx)

            # Subject position varies by layout
            if layout == "centered_dramatic":
                cx = w * 0.5
                composition_info["camera_angle"] = "low"
            elif layout == "low_angle":
                cx = w * 0.5
                composition_info["camera_angle"] = "low"
            elif layout == "rule_of_thirds":
                cx = rng.choice([w // 3, 2 * w // 3])
                composition_info["camera_angle"] = "eye_level"
            elif layout == "high_angle":
                cx = w * 0.5
                composition_info["camera_angle"] = "high"
            else:  # wide_environmental
                cx = w * rng.uniform(0.25, 0.75)
                composition_info["camera_angle"] = "high"

            cy = ground_y - 180 * element_scale
            composition_info["subject_position"] = (cx, cy)
            draw_character(d, rng, cx, cy, character_scale, outfit, headwear, mood, pose, phase)

    motion = (0.0, 12 * base_scale, 0.0, 2.6)  # gentle in-place bob
    return base, paint, motion, composition_info'''

if old_land_paint in content:
    content = content.replace(old_land_paint, new_land_paint)
    print("Replaced land paint")

# Update generate_scene_image
old_gen_image = '''def generate_scene_image(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    subject_fallback: Optional[str] = None,
) -> Path:
    rng = random.Random(index)
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, _motion = _compose_scene(rng, scene, config, subject)
    paint(ImageDraw.Draw(base))
    out_path = work_dir / f"scene_{index:02d}_illustration.jpg"
    base.save(out_path, quality=90)
    return out_path'''

new_gen_image = '''def generate_scene_image(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    subject_fallback: Optional[str] = None,
) -> Path:
    rng = random.Random(index)
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, _motion, _comp = _compose_scene(rng, scene, config, subject)
    paint(ImageDraw.Draw(base))
    out_path = work_dir / f"scene_{index:02d}_illustration.jpg"
    base.save(out_path, quality=90)
    return out_path'''

if old_gen_image in content:
    content = content.replace(old_gen_image, new_gen_image)
    print("Replaced generate_scene_image")

# Update generate_scene_clip
old_gen_clip = '''    rng = random.Random(index)
    w, h = config.video.resolution
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, (ax, ay, px, py) = _compose_scene(rng, scene, config, subject)'''

new_gen_clip = '''    rng = random.Random(index)
    w, h = config.video.resolution
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, (ax, ay, px, py), _comp = _compose_scene(rng, scene, config, subject)'''

if old_gen_clip in content:
    content = content.replace(old_gen_clip, new_gen_clip)
    print("Replaced generate_scene_clip")

with open(r"C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\procedural_illustration.py", "w") as f:
    f.write(content)

print("File written successfully")