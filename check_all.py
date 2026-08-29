with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
import re
matches = list(re.finditer(rb'"""', content))
for i, m in enumerate(matches):
    print(f'  {i}: pos={m.start()}, context={content[m.start():m.start()+50]}')