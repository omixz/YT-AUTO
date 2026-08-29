with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def concat_audio')
doc_idx = content.find(b'"""', idx)
print('doc_idx:', doc_idx)
end_idx = content.find(b'"""', doc_idx + 3)
print('end_idx:', end_idx)
if end_idx >= 0:
    docstring = content[doc_idx:end_idx+3]
    print('Docstring:', repr(docstring))
    print('Ends with """', docstring.endswith(b'"""'))