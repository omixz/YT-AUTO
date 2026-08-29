with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def _apply_expressiveness')
doc_idx = content.find(b'"""', idx)
end_idx = content.find(b'"""', idx + 3)
print('doc_idx:', doc_idx)
print('end_idx:', end_idx)
if end_idx >= 0:
    print('Docstring:', repr(content[doc_idx:end_idx+3]))
else:
    print('UNCLOSED!')
print('---')
print('Raw bytes:', content[3877:4000])