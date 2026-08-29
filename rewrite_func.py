with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the synthesize_script function and replace it
new_func = '''def synthesize_script(
    script: Script, voice: VoiceConfig, work_dir: Path, google_api_key: Optional[str] = None,
) -> Tuple[List[SceneAudio], Path]:
    \"\"\"Synthesize narration for the scene.\"\"\"
    scenes: List[SceneAudio] = []
    synthesize_one = _resolve_synthesizer(voice, google_api_key)

    for i, scene in enumerate(script.scenes):
        out_path = work_dir / f\"scene_{i:02d}.mp3\"
        cues = synthesize_one(scene.narration, out_path, scene.role)
        duration = _probe_duration(out_path)
        scenes.append(SceneAudio(scene_index=i, audio_path=out_path, duration=duration, cues=cues))

    full_narration = concat_audio([s.audio_path for s in scenes], work_dir / \"narration_full.mp3\")
    return scenes, full_narration

'''

new_lines = []
i = 0
while i < len(lines):
    if 'def synthesize_script' in lines[i]:
        # Skip the old function
        while i < len(lines) and not (lines[i].strip() == 'def silent_audio' or (lines[i].startswith('def ') and 'synthesize_script' not in lines[i])):
            i += 1
        # Insert new function
        new_lines.append(new_func)
    else:
        new_lines.append(lines[i])
        i += 1

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Rewrote function')