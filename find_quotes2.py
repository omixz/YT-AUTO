import re

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

matches = list(re.finditer(rb'"""', content))
print(f'Total triple quotes: {len(matches)}')
for i, m in enumerate(matches):
    context = content[m.start():m.start()+50]
    print(f'{i}: pos={m.start()}, context={context!r}')