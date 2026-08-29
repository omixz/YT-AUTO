with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
import re
funcs = list(re.finditer(r'def\s+\w+\s*\(', source))
for i, m in enumerate(funcs):
    func_start = m.start()
    func_name = source[m.start():m.end()]
    func_end = source.find('\n', m.end())
    if func_end == -1:
        func_end = len(source)
    func_body_start = func_end + 1
    doc_start = source.find('"""', m.end())
    if doc_start >= 0 and doc_start < source.find('\n', m.end()) + 200:
        doc_end = source.find('"""', doc_start + 3)
        if doc_end >= 0:
            docstring = source[doc_start:doc_end+3]
            print(f'{m.group()[:50]}... docstring: {repr(docstring[:80])}')
        else:
            print(f'{m.group()[:50]}... NO DOCSTRING')
            if doc_start >= 0:
                print(f'  UNCLOSED DOCSTRING at pos {doc_start}')
    else:
        print(f'{m.group()[:50]}... NO DOCSTRING')