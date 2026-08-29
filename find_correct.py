with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
# Search for closing """ AFTER the opening """
end_idx = content.find(b'"""', doc_idx + 3)
print('doc_idx:', doc_idx)
print('end_idx:', end_idx)
if end_idx >= 0:
    docstring = content[doc_idx:end_idx+3]
    print('Docstring:', repr(docstring))
    print('Length:', len(docstring))
    print('Ends with """', docstring.endswith(b'"""'))