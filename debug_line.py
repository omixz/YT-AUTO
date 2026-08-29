with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
line = lines[254]  # line 255
print('Line 255:', repr(line))
print('Contains backslash:', '\\\\' in line)
print('Contains single quote:', \"'\" in line)
# Check each character
for i, ch in enumerate(line):
    if ch == '\\\\' or ch == \"'\":
        print(f'  Pos {i}: {repr(ch)}')