import re

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Fix the escaped single quote in synthesize_script docstring
# Find: b'    """Synthesize every scene\\\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
# Replace with: b'    """Synthesize every scene\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
old = b'    """Synthesize every scene\\\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
new = b'    """Synthesize every scene\'s narration, returning per-scene audio and a\r\n    single concatenated narration track for the final mix."""'
content = content.replace(old, new)

# Also fix the concat_audio one if not already fixed
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(content)
print('Fixed')