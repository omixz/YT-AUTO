import os
os.chdir(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO')
print(os.getcwd())

with open(r'youtube_automation/tts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print('Line 112 before:', repr(lines[111]))
lines[111] = lines[111].replace('.replace(\'"\', \'"""\')', '.replace(\'"\', \'"\')')

with open(r'youtube_automation/tts.py', 'w', encoding='utf-8', newline='\n') as f:
    f.writelines(lines)

print('Fixed')