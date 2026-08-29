docstring = '''"""Synthesize every scene's narration, returning per-scene audio and a
    single concatenated narration track for the final mix."""'''
try:
    compile(docstring, 'test', 'exec')
    print('Compiles OK')
except SyntaxError as e:
    print('Error:', e)