with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

idx = source.find('.replace("', '"')
if idx >= 0:
    print('Found at:', idx)
    print(repr(source[idx:idx+100]))
else:
    print('Not found with first pattern')

idx2 = source.find('.replace("' + chr(34) + chr(34) + chr(34) + ')')
if idx2 >= 0:
    print('Found alt at:', idx2)
    print(repr(source[idx2:idx2+100]))