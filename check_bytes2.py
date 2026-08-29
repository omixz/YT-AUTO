with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
for i in range(4420, 4440):
    b = content[i]
    print(f'{i}: {hex(b)} ({chr(b) if 32 <= b < 127 else "?"})')