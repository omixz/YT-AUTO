import numpy as np
from youtube_automation import music, sound_effects as sfx
from youtube_automation.script_writer import Scene


def test_same_sound_in_two_scenes_is_not_an_identical_waveform():
    sfx._SCENE_SEED[0] = 1
    a = sfx._synth_horse(3.0)
    sfx._SCENE_SEED[0] = 2
    b = sfx._synth_horse(3.0)
    sfx._SCENE_SEED[0] = 1
    c = sfx._synth_horse(3.0)
    assert not np.allclose(a, b)      # different scenes differ
    assert np.allclose(a, c)          # but a scene is reproducible
    sfx._SCENE_SEED[0] = 0


def test_whooshes_vary_by_seed():
    assert not np.allclose(sfx._synth_transition_whoosh(0.6, seed=1), sfx._synth_transition_whoosh(0.6, seed=2))


def test_build_to_build_transitions_are_thinned(tmp_path):
    roles = ["hook"] + ["build"] * 12 + ["insight"]
    p = sfx.build_transition_sfx(roles, [10.0] * len(roles), tmp_path)
    import wave
    with wave.open(str(p)) as f:
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    sr = sfx.SAMPLE_RATE
    hits = sum(1 for i in range(len(roles) - 1) if np.abs(x[int((10 * (i + 1) - 0.6) * sr):int(10 * (i + 1) * sr)]).max() > 200)
    assert hits < len(roles) - 1 and hits >= 4   # fewer than one per boundary, still present


def test_music_does_not_repeat_every_24_seconds(tmp_path):
    p = music.build_music_bed(150.0, tmp_path)
    import wave
    with wave.open(str(p)) as f:
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(float)
    sr = music.SAMPLE_RATE
    a, b = x[30 * sr:54 * sr], x[54 * sr:78 * sr]   # one fixed-loop period apart
    assert not np.allclose(a, b, atol=500)
    assert len(x) >= 150 * sr
