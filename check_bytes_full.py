with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
line = lines[258]
for i, b in enumerate(line):
    print(f'{i}: {hex(b)} ({chr(b) if 32 <= b < 127 else "?"})')