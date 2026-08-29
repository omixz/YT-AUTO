with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
raw = content[doc_idx:end_idx+3]
print('Raw length:', len(raw))
for i, b in enumerate(content[10323:10500]):
    if i > 180:
        break
    print(f'{10323+i}: {hex(b)} ({chr(b) if 32 <= b < 127 else "?"})')