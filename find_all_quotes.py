with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
import re
matches = list(re.finditer(r'"""', source))
for i, m in enumerate(matches):
    context = source[m.start():m.start()+50]
    print(f'{i}: pos={m.start()}, context={repr(context)}')