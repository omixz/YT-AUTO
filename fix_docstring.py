with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix: make the docstring single-line
lines[258] = '    """Synthesize every scene\'s narration, returning per-scene audio and a single concatenated narration track for the final mix."""\n'

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Fixed docstring to single line')