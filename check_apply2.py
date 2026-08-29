with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('def _apply_expressiveness')
print('def at:', idx)
doc_start = source.find('"""', idx)
print('doc_start:', idx)
doc_end = source.find('"""', idx + 3)
print('doc_end:', doc_end)
if doc_end >= 0:
    print('Docstring:', repr(source[doc_start:doc_end+3]))
else:
    print('UNCLOSED!')