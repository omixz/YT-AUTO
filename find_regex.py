import re
with open(r'youtube_automation/tts.py', 'rb') as f:
    content = f.read()
matches = list(re.finditer(rb'\.replace\(.*?\".*?\"""', content))
for m in matches:
    print(f'Found at {m.start()}: {repr(content[m.start():m.end()+50])}')