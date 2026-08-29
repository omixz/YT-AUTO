with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
line = lines[259]  # line 260 (0-indexed)
print('Line 260 repr:', repr(line))
print('Line length:', len(line))
print('Starts with triple quote:', line.startswith('"""'))
idx = line.find('"""')
print('First triple quote at:', idx)