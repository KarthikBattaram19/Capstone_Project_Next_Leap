"""scripts/prepare_recordings.py on synthetic recordings shaped like Windows Sound Recorder's.

Each file is what a real session produced on 2026-09-16: 48 kHz stereo, silence before the
speech, the speech, a gap while the hand moves to Stop, then the click of Stop itself. No
microphone, no provider, no production.
"""

import hashlib
import importlib.util
import sys
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "prepare_recordings", REPO / "scripts" / "prepare_recordings.py"
)
pr = importlib.util.module_from_spec(_spec)
sys.modules["prepare_recordings"] = pr
_spec.loader.exec_module(pr)

_spike_spec = importlib.util.spec_from_file_location(
    "latency_spike", REPO / "scripts" / "latency_spike.py"
)
latency_spike = importlib.util.module_from_spec(_spike_spec)
_spike_spec.loader.exec_module(latency_spike)

SRC_RATE = 48000
WORDS_PER_S = 3.5
LEAD_S = 0.3
GAP_BEFORE_STOP_S = 0.7
CLICK_S = 0.04


def tone(seconds: float, dbfs: float = -12.0, freq: float = 440.0, rate: int = SRC_RATE):
    t = np.arange(round(seconds * rate)) / rate
    return 10 ** (dbfs / 20) * 32767 * np.sin(2 * np.pi * freq * t)


def silence(seconds: float, rate: int = SRC_RATE):
    return np.zeros(round(seconds * rate))


def speech_seconds(say: str) -> float:
    words = pr.spoken_words(say)
    return 0.5 if words == 1 else words / WORDS_PER_S


def recording(say: str, *, pause_s: float = 0.0, speech_dbfs: float = -12.0) -> np.ndarray:
    """Lead silence, the "speech" (with an optional pause in the middle), the gap, the click.
    The click is only 8 dB below the speech, so it is removed by the Stop rule, not as faint noise."""
    s = speech_seconds(say)
    if pause_s:
        body = np.concatenate(
            [tone(s / 2, speech_dbfs), silence(pause_s), tone(s / 2, speech_dbfs)]
        )
    else:
        body = tone(s, speech_dbfs)
    return np.concatenate(
        [silence(LEAD_S), body, silence(GAP_BEFORE_STOP_S), tone(CLICK_S, -20.0, freq=2000.0)]
    )


def write_wav(path: Path, mono: np.ndarray, rate: int = SRC_RATE, channels: int = 2) -> None:
    pcm = np.clip(np.rint(mono), -32768, 32767).astype("<i2")
    frames = np.repeat(pcm[:, None], channels, axis=1).reshape(-1) if channels == 2 else pcm
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.astype("<i2").tobytes())


def make_set(folder: Path, **override) -> dict[str, str]:
    """All the plan's recordings in `folder`; `override` maps a file name to its samples."""
    folder.mkdir(parents=True, exist_ok=True)
    says = {s.wav: s.say for s in pr.load_plan_steps()}
    for wav, say in says.items():
        write_wav(folder / wav, override.get(wav, recording(say)))
    return says


# ---- the list of recordings


def test_the_recording_list_is_the_timing_scripts_own_plan():
    """If timed_interactions adds, renames or rewords a recording, this script follows."""
    steps = pr.load_plan_steps()
    assert {s.wav for s in steps} == {
        "brief-1.wav",
        "brief-2.wav",
        "brief-3.wav",
        "yes.wav",
        "why-first.wav",
        "area-first.wav",
        "book-first.wav",
        "refine.wav",
    }
    assert all(s.say for s in steps)


def test_words_are_counted_as_spoken_not_as_written():
    assert (
        pr.spoken_words(
            "I'm looking for a 2 BHK in Koramangala under 40,000 rupees, and I need parking"
        )
        == 18
    )
    assert pr.spoken_words("Show me a 2 BHK in HSR Layout under 50,000") == 15
    assert pr.spoken_words("Yes") == 1


# ---- what gets written


def test_a_sound_recorder_file_becomes_what_the_driver_accepts(tmp_path):
    src, out = tmp_path / "recorded", tmp_path / "out"
    says = make_set(src)

    assert pr.main([str(src), "--out", str(out)]) == 0

    for wav in says:
        latency_spike.read_pcm16(out / wav)  # asserts 16 kHz, mono, 16-bit
        with wave.open(str(out / wav)) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)


def test_the_stop_click_and_the_silence_after_speech_are_cut(tmp_path):
    """The driver starts every latency clock at the last frame it sends. Anything after the
    last word - the gap, the click - would start that clock late and flatter every number."""
    src, out = tmp_path / "recorded", tmp_path / "out"
    says = make_set(src)
    pr.main([str(src), "--out", str(out)])

    for wav, say in says.items():
        with wave.open(str(out / wav)) as w:
            got = w.getnframes() / w.getframerate()
        expected = pr.LEAD_S + speech_seconds(say) + pr.TAIL_S
        assert abs(got - expected) <= 0.06, f"{wav}: {got:.2f}s, expected {expected:.2f}s"
        assert got < LEAD_S + speech_seconds(say) + GAP_BEFORE_STOP_S, f"{wav}: the gap was kept"


def test_the_conversion_does_not_change_the_speech_level():
    x = tone(1.0, -12.0, freq=1000.0)
    y = pr.to_16k(x, SRC_RATE)
    edge_in, edge_out = int(0.05 * SRC_RATE), int(0.05 * 16000)  # skip the filter's edges
    rms_in = np.sqrt((x[edge_in:-edge_in] ** 2).mean())
    rms_out = np.sqrt((y[edge_out:-edge_out] ** 2).mean())
    assert abs(20 * np.log10(rms_out / rms_in)) < 0.1


def test_a_16khz_mono_recording_is_passed_through_unresampled(tmp_path):
    src, out = tmp_path / "recorded", tmp_path / "out"
    says = make_set(src)
    brief = recording(says["brief-2.wav"])[::3]  # already 16 kHz
    write_wav(src / "brief-2.wav", brief, rate=16000, channels=1)

    assert pr.main([str(src), "--out", str(out)]) == 0
    latency_spike.read_pcm16(out / "brief-2.wav")


# ---- when nothing is written


def test_a_pause_long_enough_to_split_the_sentence_writes_nothing(tmp_path, capsys):
    src, out = tmp_path / "recorded", tmp_path / "out"
    says = make_set(src)
    write_wav(src / "brief-2.wav", recording(says["brief-2.wav"], pause_s=1.1))

    assert pr.main([str(src), "--out", str(out)]) == 1
    assert not out.exists() or not any(out.iterdir()), "a partial set was written"
    assert "split the sentence" in capsys.readouterr().out


def test_clipping_writes_nothing(tmp_path, capsys):
    src, out = tmp_path / "recorded", tmp_path / "out"
    says = make_set(src)
    loud = np.clip(recording(says["refine.wav"], speech_dbfs=+6.0), -32768, 32767)
    write_wav(src / "refine.wav", loud)

    assert pr.main([str(src), "--out", str(out)]) == 1
    assert "clipped" in capsys.readouterr().out


def test_a_long_recording_saved_as_yes_is_caught_as_the_wrong_file(tmp_path, capsys):
    src, out = tmp_path / "recorded", tmp_path / "out"
    says = make_set(src)
    write_wav(src / "yes.wav", recording(says["brief-1.wav"]))  # a whole brief, named yes.wav

    assert pr.main([str(src), "--out", str(out)]) == 1
    assert "right file" in capsys.readouterr().out


def test_an_unsupported_sample_rate_is_a_plain_error_not_a_traceback(tmp_path, capsys):
    src = tmp_path / "recorded"
    says = make_set(src)
    write_wav(src / "brief-1.wav", recording(says["brief-1.wav"]), rate=44100)

    assert pr.main([str(src), "--out", str(tmp_path / "out")]) == 2
    assert "44100 Hz" in capsys.readouterr().err


def test_a_missing_recording_is_named(tmp_path, capsys):
    src = tmp_path / "recorded"
    make_set(src)
    (src / "why-first.wav").unlink()

    assert pr.main([str(src), "--out", str(tmp_path / "out")]) == 2
    assert "why-first.wav" in capsys.readouterr().err


def test_check_only_writes_nothing(tmp_path):
    src, out = tmp_path / "recorded", tmp_path / "out"
    make_set(src)
    assert pr.main([str(src), "--out", str(out), "--check-only"]) == 0
    assert not out.exists()


def test_the_originals_are_never_modified(tmp_path):
    src, out = tmp_path / "recorded", tmp_path / "out"
    make_set(src)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir()}
    pr.main([str(src), "--out", str(out)])
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir()}
    assert before == after
