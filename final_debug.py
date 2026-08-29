import ast

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
source = content.decode('utf-8')

try:
    compile(source, 'tts.py', 'exec')
    print('Compile OK')
except SyntaxError as e:
    print('Error:', e)
    print('Line:', e.lineno)
    print('Offset:', e.offset)
    print('Text:', repr(e.text))
    lines = source.splitlines()
    for i in range(max(0, e.lineno-5), min(len(lines), e.lineno+5)):
        print(f'{i+1}: {repr(lines[i])}')