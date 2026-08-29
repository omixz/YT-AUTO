with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def _apply_expressiveness')
doc_idx = content.find(b'"""', idx)
end_idx = content.find(b'"""', idx + 3)
while end_idx != -1:
    print(f'Found at {end_idx}: {content[end_idx:end_idx+50]}')
    end_idx = content.find(b'"""', end_idx + 3)