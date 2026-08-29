# Rewrite the synthesize_script function cleanly
with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the synthesize_script function and replace it entirely
old_func = '''def synthesize_script(
    script: Script, voice: VoiceConfig, work_dir: Path, google_api_key: Optional[str] = None,
) -> Tuple[List[SceneAudio], Path]:
    """Synthesize every scene's narration, returning per-scene audio and a
    single concatenated narration track for the final mix."""
    work_dir.mkdir(parents=True, exist_ok=True)
    scenes: List[SceneAudio] = []
    synthesize_one = _resolve_synthesizer(voice, google_api_key)

    for i, scene in enumerate(script.scenes):
        out_path = work_dir / f"scene_{i:02d}.mp3"
        cues = synthesize_one(scene.narration, out_path, scene.role)
        duration = _probe_duration(out_path)
        scenes.append(SceneAudio(scene_index=i, audio_path=out_path, duration=duration, cues=cues))

    full_narration = concat_audio([s.audio_path for s in scenes], work_dir / "narration_full.mp3")
    return scenes, full_narration'''

new_func = '''def synthesize_script(
    script: Script, voice: VoiceConfig, work_dir: Path, google_api_key: Optional[str] = None,
) -> Tuple[List[SceneAudio], Path]:
    """Synthesize every scene's narration, returning per-scene audio and a
    single concatenated narration track for the final mix."""
    work_dir.mkdir(parents=True, exist_ok=True)
    scenes: List[SceneAudio] = []
    synthesize_one = _resolve_synthesizer(voice, google_api_key)

    for i, scene in enumerate(script.scenes):
        out_path = work_dir / f"scene_{i:02d}.mp3"
        cues = synthesize_one(scene.narration, out_path, scene.role)
        duration = _probe_duration(out_path)
        scenes.append(SceneAudio(scene_index=i, audio_path=out_path, duration=duration, cues=cues))

    full_narration = concat_audio([s.audio_path for s in scenes], work_dir / "narration_full.mp3")
    return scenes, full_narration'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Replaced synthesize_script function')
else:
    print('Old function not found - searching...')
    # Try to find it with more flexible matching
    import re
    pattern = r'def synthesize_script\(.*?"""Synthesize every scene.*?return scenes, full_narration'
    match = re.search(pattern, content, re.DOTALL)
    if match:
        print('Found with regex')
    else:
        print('Not found with regex either')