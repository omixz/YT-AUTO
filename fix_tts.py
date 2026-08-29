import os
os.chdir(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO')
print(os.getcwd())

with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

# Find the problematic line
idx = source.find('.replace("', '"""')')
if idx >= 0:
    print('Found at:', idx)
    print(repr(source[idx:idx+100]))
else:
    print('Not found')