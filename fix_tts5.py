with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Fix the escaped single quote in synthesize_script docstring
# The pattern is: scene\'s  (backslash + quote)
# Need to replace with scene's  (just the quote)
content = content.replace(b"scene\\'s", b"scene's")

# Also fix the concat_audio one if not already fixed
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(content)
print('Fixed')