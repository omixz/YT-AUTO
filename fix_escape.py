with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

# Fix the problematic line: .replace('"', """) -> .replace('"', '"')
source = source.replace('.replace(\'"\', \'"""\')', '.replace(\'"\', \'"\')')

with open(r'youtube_automation/tts.py', 'w', encoding='utf-8') as f:
    f.write(source)

print('Fixed')