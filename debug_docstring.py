import re

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()

idx = source.find('def synthesize_script')
doc_idx = source.find('"""Synthesize', idx)
print('doc_idx:', doc_idx)
end_idx = source.find('"""', idx + 3)
print('end_idx:', end_idx)

if end_idx >= 0:
    docstring = source[idx:end_idx+3]
    print('Docstring:', repr(docstring))
    print('Ends with \"\"\"', docstring.endswith('"""'))