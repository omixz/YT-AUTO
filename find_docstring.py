with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
print('def idx:', idx)
# Find the opening """ after the function signature
doc_idx = content.find(b'"""', idx)
print('first """ at:', doc_idx)
# Find the next """ after the opening
end_idx = content.find(b'"""', doc_idx + 3)
print('end_idx:', end_idx)
raw = content[doc_idx:end_idx+3]
print('Docstring:', repr(content[doc_idx:idx+200]))