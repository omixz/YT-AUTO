with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Find the docstring
idx = content.find(b'def synthesize_script')
doc_idx = content.find(b'"""Synthesize', idx)
end_idx = content.find(b'"""', doc_idx + 3)

print('doc_idx:', doc_idx)
print('end_idx:', end_idx)
docstring = content[doc_idx:end_idx+3]
print('Docstring:', repr(docstring))

# Find the exact problematic bytes
# Look for scene followed by backslash quote s
problem_idx = content.find(b"scene\\'s", doc_idx)
if problem_idx >= 0:
    print('Found problem at:', problem_idx)
    print(repr(content[problem_idx:problem_idx+10]))
else:
    print('Not found with that pattern')
    # Try to find scene followed by any backslash
    for i in range(doc_idx, end_idx):
        if content[i:i+6] == b"scene\\":
            print('Found at', i, repr(content[i:i+10]))

# Now do a simple byte replacement
# Find all occurrences of b"scene\\'s" and replace with b"scene's"
content = content.replace(b"scene\\'s", b"scene's")
print('Replaced scene\\\'s with scene\'s')

# Also fix the concat_audio one
content = content.replace(b"encoder padding doesn't accumulate", b"encoder padding does not accumulate")

with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'wb') as f:
    f.write(content)
print('Done')