with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Check bytes around the issue
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
print('doc_idx:', doc_idx)
print('Bytes at doc_idx:', repr(content[doc_idx:doc_idx+80]))
print()
# Check the exact bytes for 'scene'
scene_idx = content.find(b'scene', doc_idx)
print('scene_idx:', scene_idx)
print('Bytes around scene:', repr(content[scene_idx:scene_idx+20]))