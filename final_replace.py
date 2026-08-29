with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The issue: the file has "scene\'s" (literal backslash + quote) 
# Need to replace with "scene's" (no backslash)
# The problem is the file literally contains a backslash character before the quote
content = content.replace("scene\\'s", "scene's")

# Also fix concat_audio docstring
content = content.replace("encoder padding doesn't accumulate", "encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed')