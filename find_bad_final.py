with open(r'youtube_automation/tts.py', 'rb') as f:
    content = f.read()

# The problematic pattern is .replace('"', """) which in bytes is:
# b'.replace("' + b'"' + b'"""' + b')'
pattern = b'.replace(' + b'"' + b'"""' + b')'
idx = content.find(pattern)

if idx >= 0:
    print('Found at:', idx)
    print(repr(content[idx:idx+200]))
else:
    print('Not found with first pattern')

    # Try alternative
    idx2 = content.find(b'.replace(b"', b'"""')
    if idx2 >= 0:
        print('Found alt at:', idx2)
        print(repr(content[idx2:idx2+200]))
    else:
        print('Not found with second pattern either')