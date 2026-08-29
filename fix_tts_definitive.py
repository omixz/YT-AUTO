with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The issue: the file contains scene\'s which has a backslash
# Python interprets \' as escaped quote, causing issues with triple-quoted strings
# Replace scene\'s with scene's (no backslash)
content = content.replace("scene\\'s", "scene's")

# Also fix concat_audio
content = content.replace("encoder padding doesn't accumulate", "encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed')