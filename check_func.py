with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('def synthesize_one')
if idx == -1:
    idx = source.find('def _synthesize_one')
print('Function idx:', idx)
if idx >= 0:
    print(repr(source[idx:idx+200]))