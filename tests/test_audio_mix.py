import shutil, subprocess
from pathlib import Path
import pytest
from youtube_automation.assembler import _build_mix_command

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _mk(tmp: Path):
    def run(args):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)
    v, n, m, a, t = (tmp / x for x in ("v.mp4", "n.mp3", "m.wav", "a.wav", "t.wav"))
    run(["-f", "lavfi", "-i", "color=c=black:s=160x90:d=2:r=10", str(v)])
    run(["-f", "lavfi", "-i", "sine=f=440:r=24000:d=2,aformat=channel_layouts=mono", str(n)])  # like edge-tts: 24k mono
    run(["-f", "lavfi", "-i", "anoisesrc=r=44100:d=2:a=0.1,aformat=channel_layouts=stereo", str(m)])
    run(["-f", "lavfi", "-i", "anoisesrc=r=44100:d=2:a=0.05,aformat=channel_layouts=stereo", str(a)])
    run(["-f", "lavfi", "-i", "sine=f=880:r=44100:d=2,aformat=channel_layouts=stereo", str(t)])
    return v, n, m, a, t


def _probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=sample_rate,channels", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return out


@pytest.mark.parametrize("beds", [(), ("m",), ("m", "a"), ("m", "a", "t"), ("t",)])
def test_mix_is_48k_stereo_for_every_bed_combination(tmp_path, beds):
    v, n, m, a, t = _mk(tmp_path)
    out = tmp_path / "out.mp4"
    cmd = _build_mix_command(v, n, m if "m" in beds else None, a if "a" in beds else None,
                             t if "t" in beds else None, out)
    subprocess.run(cmd + [], check=True, capture_output=True)
    assert _probe(out) == "48000,2"
