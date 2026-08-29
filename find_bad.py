with open(r'youtube_automation/tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'.replace(b"', b'"""')
if idx < 0:
    idx = content.find(b'.replace(b"', b'"""')
if idx >= 0:
    print('Found at:', idx)
    print(repr(content[idx:idx+200]))
else:
    print('Not found')