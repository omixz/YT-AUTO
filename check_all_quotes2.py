with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
import re
matches = list(re.finditer(r'"""', source))
print(f'Total triple quotes: {len(matches)}')
for i, m in enumerate(matches):
    print(f'  {i}: pos={m.start()}, context={source[m.start():m.start()+50]}')