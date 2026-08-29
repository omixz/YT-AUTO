with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', idx + 3)
print('end_idx:', end_idx)
if end_idx >= 0:
    print('Closing bytes:', content[end_idx:end_idx+3])
    print('Next bytes:', content[end_idx+3:end_idx+10])