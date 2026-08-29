with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
raw = content[doc_idx:end_idx+3]
print('Raw length:', len(raw))
for i, b in enumerate(raw):
    if b >= 128:
        print(f'Non-ASCII at {i}: {hex(b)}')
    if b == 0x5c:
        print(f'Backslash at {i}')
    if b == 0x27:
        print(f'Quote at {i}')