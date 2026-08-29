with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
raw = content[doc_idx:end_idx+3]
print('Raw:', repr(raw))
try:
    compile(raw.decode('utf-8'), 'test', 'exec')
    print('Compiles OK')
except SyntaxError as e:
    print('Error:', e)