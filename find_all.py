with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
print('def idx:', idx)
# Find ALL occurrences of """ after the function
pos = idx
count = 0
while True:
    pos = content.find(b'"""', pos)
    if pos == -1:
        break
    print(f'Found """ at {pos}: {content[pos:pos+60]}')
    pos += 1