import wave

import numpy as np

from youtube_automation import music


def _read(path):
    with wave.open(str(path)) as f:
        fr, n = f.getframerate(), f.getnframes()
        pcm = np.frombuffer(f.readframes(n), dtype=np.int16).astype(float) / 32768
    return fr, n, pcm


def test_music_bed_is_long_enough(tmp_path):
    bed = music.build_music_bed(30.0, tmp_path)
    fr, n, _ = _read(bed)
    assert n / fr >= 30.0


def test_music_bed_is_audible_but_not_clipping(tmp_path):
    _, _, pcm = _read(music.build_music_bed(12.0, tmp_path))
    assert np.max(np.abs(pcm)) <= 1.0          # no clipping
    assert np.sqrt(np.mean(pcm ** 2)) > 0.05   # actually audible, not silence


def test_music_bed_handles_short_duration(tmp_path):
    # A very short video shouldn't crash the segment loop.
    bed = music.build_music_bed(0.3, tmp_path)
    assert bed.exists()
