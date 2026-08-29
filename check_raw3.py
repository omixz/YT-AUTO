with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
raw = content[doc_idx:idx+3]
print('Raw docstring length:', len(raw))
for i, b in enumerate(raw):
    if b >= 128:
        print(f'Non-ASCII at {i}: {hex(b)}')
    if b == 0x5c:  # backslash
        print(f'Backslash at {i}')
    if b == 0x27:  # single quote
        print(f'Quote at {i}')
    if b == 0x22:  # double quote
        print(f'Double quote at {i}')
    if b == 0x0d:  # CR
        print(f'CR at {i}')
    if b == 0x0a:  # LF
        print(f'LF at {i}')