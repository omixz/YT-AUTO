with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    content = f.read()

print('Contains scene quote s:', "scene's" in content)
print('Contains scene backslash s:', "scene\\'s" in content)