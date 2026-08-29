with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i in range(108, 120):
    print(f'{i+1}: {repr(lines[i])}')