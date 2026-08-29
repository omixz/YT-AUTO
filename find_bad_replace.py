with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Search for the problematic pattern
idx = content.find(b'.replace(b"', b'"""')
if idx < 0:
    idx = content.find(b'.replace(b"', b'"""')
    
if idx >= 0:
    print('Found at:', idx)
    print(repr(content[idx:idx+100]))
else:
    print('Not found with first pattern')
    
# Also try alternative
idx2 = content.find(b'.replace("', b'"""')
if idx2 >= 0:
    print('Found alt at:', idx2)
    print(repr(content[idx2:idx2+100]))