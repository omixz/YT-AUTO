import ast
import os
import sys

for root, dirs, files in os.walk('.'):
    if '__pycache__' in root or '.git' in root or '.pytest_cache' in root:
        continue
    for f in files:
        if f.endswith('.py') and not f.startswith('.'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    source = f.read()
                try:
                    compile(source, path, 'exec')
                except SyntaxError as e:
                    print(f'Syntax error in {path}: {e}')
            except UnicodeDecodeError:
                print(f'Binary file: {path}')
            except Exception as e:
                print(f'Error reading {path}: {e}')

print('Syntax check complete')