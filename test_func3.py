import ast
with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
func_text = content[content.find(b'def synthesize_script'):content.find(b'def silent_audio')]
try:
    ast.parse(func_text.decode('utf-8'))
    print('Function OK')
except SyntaxError as e:
    print('Function error:', e)
    print('Line:', e.lineno)
    print('Offset:', e.offset)