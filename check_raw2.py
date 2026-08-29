with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
docstring = content[doc_idx:end_idx+3]
scene_idx = docstring.find(b'scene')
abs_idx = doc_idx + scene_idx
print('Absolute offset of scene:', abs_idx)
for i in range(abs_idx, abs_idx + 20):
    b = content[i]
    print(f'{i}: {hex(b)} ({chr(b) if 32 <= b < 127 else "?"})')