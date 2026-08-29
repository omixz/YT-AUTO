with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
print('doc_idx:', doc_idx)

# Check bytes around doc_idx
for i in range(doc_idx, doc_idx + 50):
    b = content[i]
    ch = chr(content[i]) if 32 <= content[i] < 127 else '?'
    print(f'{i}: {hex(content[i])} ({ch})')

# Now search for closing """
end_idx = content.find(b'"""', doc_idx + 3)
print('end_idx:', end_idx)

if end_idx >= 0:
    print('Found at:', end_idx)
    for i in range(end_idx, end_idx + 10):
        print(f'{i}: {hex(content[i])} ({chr(content[i]) if 32 <= content[i] < 127 else "?"})')