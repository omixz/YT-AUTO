import re

with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

matches = list(re.finditer(r'"""', source))
print(f'Total triple quotes: {len(matches)}')
for i, m in enumerate(matches):
    # Find line number
    line_num = source[:m.start()].count('\n') + 1
    context = source[m.start():m.start()+50]
    print(f'{i}: pos={m.start()}, line={line_num}, context={repr(source[m.start():m.start()+50])}')