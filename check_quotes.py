with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

count = source.count('"""')
print(f'Total triple quotes: {count}')
if count % 2 != 0:
    print('ODD number of triple quotes!')