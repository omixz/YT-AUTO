with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
line = lines[254]  # line 255
print('Line 255:', repr(line))
print('Length:', len(line))
print('Ends with newline:', line.endswith('\n'))
# Check for any weird characters
for i, ch in enumerate(line):
    if ord(ch) >= 128:
        print(f'Non-ASCII at {i}: {hex(ord(ch))} ({repr(ch)})')
    if ch == '\\':
        print(f'Backslash at {i}')
    if ch == "'":
        print(f'Quote at {i}')