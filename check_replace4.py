with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

# The problematic pattern is .replace('"', """) - triple quotes inside string
# Search for the pattern
pattern = '.replace("' + '"' + '""")'
idx = source.find(pattern)
if idx >= 0:
    print('Found at:', idx)
    print(repr(source[idx:idx+100]))
else:
    print('Not found with pattern')