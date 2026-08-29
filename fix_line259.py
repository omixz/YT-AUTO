with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix line 259 (index 258) - remove the backslash before the quote
lines[258] = '    """Synthesize every scene\'s narration, returning per-scene audio and a\n'

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Fixed line 259')