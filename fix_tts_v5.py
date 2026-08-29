with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# The issue: the file contains b"scene\\'s" (literal backslash + quote)
# Need to replace with b"scene's"
# Find the docstring
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', doc_idx + 3)

docstring = content[doc_idx:end_idx+3]
print('Before:', repr(docstring))

# Replace the problematic bytes directly
# The pattern is: b"scene\\'s" -> b"scene's"
content = content.replace(b"scene\\'s", b"scene's")

# Verify the fix
doc_idx2 = content.find(b'"""Synthesize', idx)
end_idx2 = content.find(b'"""', doc_idx2 + 3)
docstring2 = content[doc_idx2:end_idx2+3]
print('After:', repr(docstring2))

# Also fix the concat_audio one
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(content)
print('Done')