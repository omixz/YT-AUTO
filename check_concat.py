with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def concat_audio')
doc_idx = content.find(b'"""', idx)
print('doc_idx:', doc_idx)
doc_end = content.find(b'"""', doc_idx + 3)
print('doc_end:', doc_end)
if doc_end >= 0:
    docstring = content[doc_idx:end_idx+3]
    print('Docstring:', repr(docstring))
    print('Ends with """', docstring.endswith(b'"""'))