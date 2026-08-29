with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

# Find the problematic replace call
idx = source.find('.replace("' + chr(34) + chr(34) + chr(34) + ')')
if idx >= 0:
    print('Found at:', idx)
    print(repr(source[idx:idx+100]))
else:
    print('Not found with triple quote pattern')
    
# Also try alternative
idx2 = source.find('.replace("', '"')
if idx2 >= 0:
    print('Found alt at:', idx2)
    print(repr(source[idx2:idx2+100]))