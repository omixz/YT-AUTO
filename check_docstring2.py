with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Find the synthesize_script function
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
print('doc_idx:', doc_idx)

# Search for closing """ starting from after the opening """
end_idx = content.find(b'"""', doc_idx + 3)
print('end_idx (first search):', end_idx)

# The issue might be that find() returns the same position
# Let's search from further ahead
end_idx2 = content.find(b'"""', doc_idx + 10)
print('end_idx2:', end_idx2)

if end_idx >= 0:
    docstring = content[doc_idx:end_idx+3]
    print('Docstring:', repr(docstring))
    print('Ends with """', docstring.endswith(b'"""'))

# Also check what's at the doc_idx
print('At doc_idx:', repr(content[doc_idx:doc_idx+50]))