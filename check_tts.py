with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'rb') as f:
    content = f.read()

# Check the exact bytes around the docstring
idx = content.find(b'def synthesize_script')
if idx >= 0:
    doc_idx = content.find(b'"""Synthesize', idx)
    if doc_idx >= 0:
        print('Found docstring at:', doc_idx)
        print(repr(content[doc_idx:doc_idx+120]))
        # Check for the closing """
        end_idx = content.find(b'"""', doc_idx + 3)
        print('Closing """ at:', end_idx)
        print(repr(content[doc_idx:end_idx+3]))