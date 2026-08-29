with open(r'C:\Users\Omarn\OneDrive\Documents\Default Project\YT-AUTO\youtube_automation\tts.py', 'r', encoding='utf-8') as f:
    source = f.read()
idx = source.find('edge_tts.Communicate() native parameters (rate, pitch, volume).')
end_idx = source.find('"""', idx)
print('Found at:', end_idx)
print('Context:', repr(source[end_idx:end_idx+50]))