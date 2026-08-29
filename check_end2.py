with open(r'youtube_automation/tts.py', 'rb') as f:
    content = f.read()
for i in range(11550, 11620):
    b = content[i]
    print(f'{i}: {hex(b)} ({chr(b) if 32 <= b < 127 else "?"})')