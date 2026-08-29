with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
docstring = content[doc_idx:end_idx+3]
print('Docstring bytes:', docstring)
try:
    decoded = docstring.decode('utf-8')
    print('Decoded:', repr(decoded))
except Exception as e:
    print('Decode error:', e)