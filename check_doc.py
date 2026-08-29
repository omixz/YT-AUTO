with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
print('doc_idx:', doc_idx)
end_idx = content.find(b'"""', doc_idx + 3)
print('end_idx:', end_idx)
docstring = content[doc_idx:end_idx+3]
print('Docstring length:', len(docstring))
print('Docstring:', repr(docstring))