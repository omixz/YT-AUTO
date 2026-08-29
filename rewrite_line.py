with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Replace line 259 (index 258)
lines[258] = '    """Synthesize narration for the scene."""\n'

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'w', encoding='utf-8', newline='\r\n') as f:
    f.writelines(lines)
print('Rewrote line 259')