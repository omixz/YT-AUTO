with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r') as f:
    lines = f.readlines()

# Check lines around 255
for i, line in enumerate(lines[250:265], 251):
    print(f'{i}: {repr(line)}')