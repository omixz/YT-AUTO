import wave

import numpy as np

from youtube_automation import music


def _read(path):
    with wave.open(str(path)) as f:
        fr, n = f.getframerate(), f.getnframes()
        pcm = np.frombuffer(f.readframes(n), dtype=np.int16).astype(float) / 32768
    return fr, n, pcm


def _rms_segment(pcm, fr, t_start, t_end):
    s, e = int(t_start * fr), int(t_end * fr)
    return float(np.sqrt(np.mean(pcm[s:e] ** 2)))


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


def test_music_bed_ducks_hook_and_fades_outro(tmp_path):
    fr, _, pcm = _read(music.build_music_bed(30.0, tmp_path, scene_durations=[10, 10, 10]))
    hook_rms = _rms_segment(pcm, fr, 0.5, 1.5)
    mid_rms = _rms_segment(pcm, fr, 12.0, 14.0)
    outro_rms = _rms_segment(pcm, fr, 27.5, 29.5)
    assert hook_rms < mid_rms, "hook section should be quieter than the middle"
    assert outro_rms < mid_rms, "outro section should be quieter than the middle"


def test_music_bed_swells_at_scene_transition(tmp_path):
    fr, _, pcm = _read(music.build_music_bed(30.0, tmp_path, scene_durations=[10, 10, 10]))
    # Right at the first scene boundary (t=10s) there should be a brief swell
    at_boundary = _rms_segment(pcm, fr, 9.8, 10.2)
    away = _rms_segment(pcm, fr, 8.0, 8.4)
    assert at_boundary >= away, "music should swell at scene transition"


def test_music_bed_without_scene_durations_still_works(tmp_path):
    fr, n, pcm = _read(music.build_music_bed(12.0, tmp_path))
    assert np.max(np.abs(pcm)) <= 1.0
    assert np.sqrt(np.mean(pcm ** 2)) > 0.05
