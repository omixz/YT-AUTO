with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the escaped single quote in synthesize_script docstring
content = content.replace("scene\\'s", "scene's")

# Also fix the concat_audio docstring
content = content.replace("encoder padding doesn't accumulate", "encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed')