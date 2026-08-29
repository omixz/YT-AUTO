with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Fix: remove the backslash before the quote in "scene\'s"
# The line has: b'    """Synthesize every scene\'s narration...'
# Need to remove the backslash (0x5c) before the quote (0x27)

# Find the line
lines = content.split(b'\n')
line_259 = lines[258]  # 0-indexed, so line 259 is index 258

# Find the backslash before the quote in "scene's"
# Pattern: b"scene\'s" -> should be b"scene's"
if b"scene\\'s" in line_259:
    new_line = line_259.replace(b"scene\\'s", b"scene's")
    lines[258] = new_line
    print(f'Fixed line 259: replaced backslash-quote')
else:
    print('Pattern not found in line 259')
    print('Line 259:', line_259)

# Also fix the concat_audio docstring
content = b'\n'.join(lines)
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(b'\n'.join(lines))

print('Fixed')