with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Find the problematic sequence
idx = content.find(b"scene")
while idx >= 0:
    # Print context around each "scene"
    context = content[idx:idx+20]
    print(f"Found 'scene' at {idx}: {repr(context)}")
    idx = content.find(b"scene", idx + 1)

# Replace the problematic pattern
# The issue is b"scene\\'s" -> b"scene's"
content = content.replace(b"scene\\'s", b"scene's")

# Also fix the concat_audio docstring
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(content)
print('Fixed')