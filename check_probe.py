with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('def _probe_duration')
print('def _probe_duration at:', idx)
doc_start = source.find('"""', idx)
print('doc_start:', doc_start)
doc_end = source.find('"""', doc_start + 3)
print('doc_end:', doc_end)
if doc_end >= 0:
    print('Docstring:', repr(source[doc_start:doc_end+3]))