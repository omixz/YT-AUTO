with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
func_text = content[idx:idx+500]
try:
    ast.parse(func_text.decode('utf-8'))
    print('Function OK')
except SyntaxError as e:
    print('Function error:', e)
    print('Line:', e.lineno)
    print('Offset:', e.offset)
    func_lines = func_text.decode('utf-8').splitlines()
    for i, line in enumerate(func_lines):
        print(f'{i}: {repr(line)}')