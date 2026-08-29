with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def _apply_expressiveness')
pos = idx
for i in range(20):
    pos = content.find(b'"""', pos + 3)
    if pos == -1:
        break
    print(f'Found at {pos}: {content[pos:pos+50]}')
    if pos > idx + 500:
        break