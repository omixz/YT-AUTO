source = '''def synthesize_script(
    script: Script, voice: VoiceConfig, work_dir: Path, google_api_key: Optional[str] = None,
) -> Tuple[List[SceneAudio], Path]:
    """Synthesize every scene's narration, returning per-scene audio and a
    single concatenated narration track for the final mix."""
    work_dir.mkdir(parents=True, exist_ok=True)'''

import ast
try:
    ast.parse(source)
    print('Compiles OK')
except SyntaxError as e:
    print('Error:', e)
    print('Line:', e.lineno)