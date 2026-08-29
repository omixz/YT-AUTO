import ast

with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

try:
    ast.parse(source)
    print('OK')
except SyntaxError as e:
    print('Error:', e)
    print('Line:', e.lineno)
    print('Offset:', e.offset)
    lines = source.splitlines()
    for i in range(max(0, e.lineno-5), min(len(lines), e.lineno+5)):
        print(f'{i+1}: {repr(lines[i])}')