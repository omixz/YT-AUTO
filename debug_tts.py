with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', doc_idx + 3)
print('doc_idx:', doc_idx)
print('end_idx:', end_idx)
print('Docstring bytes:', repr(content[doc_idx:end_idx+3]))

# Check for non-ASCII
doc_bytes = content[doc_idx:end_idx+3]
for i, b in enumerate(doc_bytes):
    if b >= 128:
        print(f'Non-ASCII at offset {i}: {hex(b)}')