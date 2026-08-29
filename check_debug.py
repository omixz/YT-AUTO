with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
print('def idx:', idx)
# Look for all """ occurrences after the function definition
for i in range(idx, min(idx + 500, len(content))):
    if content[i:i+3] == b'"""':
        print(f'Found """ at {i}: {content[i:i+80]}')