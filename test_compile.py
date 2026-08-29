source = '''def f():
    """Synthesize narration for the scene."""
    pass'''
try:
    compile(source, 'test', 'exec')
    print('OK')
except SyntaxError as e:
    print('Error:', e)