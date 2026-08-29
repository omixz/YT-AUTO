with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
docstring = content[doc_idx:end_idx+3]
print('Docstring length:', len(docstring))
print('Docstring:', repr(docstring))
if b'\\' in docstring:
    print('Backslash found in docstring')
    for i, b in enumerate(docstring):
        if b == 0x5c:
            print(f'Backslash at docstring offset {i}')
        if b == 0x27:
            print(f'Quote at docstring offset {i}')