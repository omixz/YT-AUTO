import ast
source = '''def synthesize_script(
    script: Script, voice: VoiceConfig, work_dir: Path, google_api_key: Optional[str] = None,
) -> Tuple[List[SceneAudio], Path]:
    """Synthesize narration for the scene."""
    scenes: List[SceneAudio] = []
    synthesize_one = _resolve_synthesizer(voice, google_api_key)

    for i, scene in enumerate(script.scenes):
        out_path = work_dir / f"scene_{i:02d}.mp3"
        cues = synthesize_one(scene.narration, out_path, scene.role)
        duration = _probe_duration(out_path)
        scenes.append(SceneAudio(scene_index=i, audio_path=out_path, duration=duration, cues=cues))

    full_narration = concat_audio([s.audio_path for s in scenes], work_dir / "narration_full.mp3")
    return scenes, full_narration'''

try:
    ast.parse(source)
    print('Function OK')
except SyntaxError as e:
    print('Error:', e)
    print('Line:', e.lineno)
    print('Offset:', e.offset)