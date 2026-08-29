with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('.replace(\'"\', \'"""\')')
if idx >= 0:
    print('Found at:', idx)
    print(repr(source[idx:idx+100]))