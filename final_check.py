import ast
with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
try:
    ast.parse(source)
    print('AST parse: OK')
except SyntaxError as e:
    print('SyntaxError:', e)
    print('Line:', e.lineno)
    print('Offset:', e.offset)
    lines = source.splitlines()
    for i in range(max(0, e.lineno-5), min(len(source.splitlines()), e.lineno+5)):
        print(f'{i+1}: {repr(lines[i])}')