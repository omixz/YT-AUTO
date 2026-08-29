with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
line = lines[258]
print('Line 259 repr:', repr(line))
print('Line length:', len(line))
print('Starts with triple quote:', line.startswith('    """'))
idx = line.find('"""')
print('First triple quote at:', idx)
if idx >= 0:
    rest = line[idx+3:]
    idx2 = rest.find('"""')
    print('Second triple quote at:', idx + 3 + idx2 if idx2 >= 0 else 'NOT FOUND')
    if idx2 >= 0:
        between = rest[:idx2]
        print('Between quotes:', repr(between))