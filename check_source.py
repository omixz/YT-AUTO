with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('def synthesize_script')
print('def idx:', idx)
doc_idx = source.find('"""Synthesize', idx)
print('doc_idx:', doc_idx)
end_idx = source.find('"""', doc_idx + 3)
print('end_idx:', end_idx)
if doc_idx >= 0 and end_idx >= 0:
    docstring = source[doc_idx:end_idx+3]
    print('Docstring:', repr(docstring))