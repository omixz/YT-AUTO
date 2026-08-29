with open(r'youtube_automation/tts.py', 'rb') as f:
    content = f.read()
in_string = False
triple = False
i = 0
last_start = 0
while i < len(content):
    b = content[i]
    if b == 0x22:  # "
        if i + 2 < len(content) and content[i+1] == 0x22 and content[i+2] == 0x22:
            if not in_string:
                in_string = True
                triple = True
                last_start = i
            elif in_string and triple:
                in_string = False
                triple = False
            i += 2
        elif not in_string:
            in_string = True
            triple = False
        elif in_string and not triple:
            in_string = False
    elif b == 0x27:
        if not in_string:
            in_string = True
            triple = False
        elif in_string and not triple:
            in_string = False
    i += 1
if in_string:
    print('UNCLOSED at end, started at:', last_start)
else:
    print('All closed')