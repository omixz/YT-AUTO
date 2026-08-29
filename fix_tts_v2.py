with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# The issue is scene\'s should be scene's (no backslash)
# Find the exact pattern
old = b'"""Synthesize every scene\\\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
new = b'"""Synthesize every scene\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
print('Old:', repr(old))
print('New:', repr(new))

# Check if old exists
if old in content:
    print('Found old pattern')
    content = content.replace(old, new)
else:
    print('Old pattern NOT found, trying alternative...')
    # Try without the escaped backslash
    alt_old = b'"""Synthesize every scene\\\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
    print('Alt old:', repr(alt_old))
    if alt_old in content:
        print('Found alt pattern')
        content = content.replace(alt_old, new)
    else:
        print('Still not found')

# Also fix the concat_audio one
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(content)
print('Done')