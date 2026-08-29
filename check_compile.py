with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('"""Synthesize every scene')
end = source.find('"""', idx + 3)
print('Docstring found:', idx != -1 and end != -1)
if idx >= 0 and end >= 0:
    docstring = source[idx:end+3]
    print('Docstring length:', len(docstring))
    try:
        compile('"""' + docstring + '"""', 'test', 'exec')
        print('Docstring compiles OK')
    except SyntaxError as e:
        print('Docstring syntax error:', e)