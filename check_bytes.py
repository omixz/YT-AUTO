with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
doc_idx = 10324
end_idx = 10454
docstring = content[doc_idx:end_idx+3]
scene_offset = docstring.find(b'scene')
abs_offset = 10324 + scene_offset
for i in range(abs_offset + 15, abs_offset + 25):
    b = content[i]
    print(f'{i}: {hex(b)} ({chr(b) if 32 <= b < 127 else "?"})')