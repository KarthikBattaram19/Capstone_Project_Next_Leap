"""Task 4.1: check the spoken recordings and write the copies timed_interactions.py sends.

    python scripts/prepare_recordings.py "<folder with the recordings>"
    python scripts/prepare_recordings.py "<folder>" --check-only

Which files, and what each must say, come from timed_interactions.build_plan() - not from a
list kept here - so the two scripts cannot drift apart.

Each recording is converted to what the driver accepts (16 kHz, mono, 16-bit PCM; Windows
Sound Recorder saves 48 kHz stereo) and trimmed to the speech plus a small margin. The trim
is part of the measurement, not tidying: the driver starts every latency clock at the LAST
frame it sends and then pads its own silence, so silence left at the end of a recording would
start the clock after the backend had already heard the renter stop - and every number in
the latency report would come out better than the truth.

The Stop press is removed too. A recorder captures its own click: a short burst at the very
end of the file, after a real gap. Left in, it counts as speech and the gap before it is sent
inside the timed window.

Nothing is written unless every file passes: a clipped recording, or a mid-sentence pause long
enough to split the utterance (utterance_end_ms is 1000), is fixed by re-recording, not by
editing. The originals are never modified. The output folder, data/raw/recordings, is
gitignored: a voice is personal data.
"""

from __future__ import annotations

import importlib.util
import re
import struct
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "data" / "raw" / "recordings"

RATE = 16000
FRAME = 320  # 20 ms at 16 kHz
LEAD_S = 0.25  # kept before the first speech, so the onset is not clipped
TAIL_S = 0.15  # kept after the last speech, so a final consonant survives
MERGE_FRAMES = 8  # bursts under 160 ms apart are one sound: the gaps inside a word or phrase
FAINT_DB = 25  # a burst peaking this far below the loudest speech is breath or room noise
CLICK_MAX_S = 0.2  # a Stop press is short...
CLICK_GAP_S = 0.4  # ...follows a real gap...
CLICK_END_FRAMES = 3  # ...and ends at the very end of the file
SPLIT_S = 1.0  # utterance_end_ms: a pause this long ends the utterance
SPLIT_RISK_S = 0.8
RATE_WPS = (1.2, 5.0)  # outside this, the file probably holds a different sentence
YES_MAX_S = 1.5


def load_plan_steps() -> list:
    """The voice steps of timed_interactions' plan, one per distinct recording."""
    path = REPO / "scripts" / "timed_interactions.py"
    spec = importlib.util.spec_from_file_location("timed_interactions", path)
    ti = importlib.util.module_from_spec(spec)
    sys.modules["timed_interactions"] = ti  # dataclasses resolve string annotations through it
    spec.loader.exec_module(ti)
    seen, steps = set(), []
    for s in ti.build_plan("renter@example.com"):  # the address plays no part in a voice step
        if s.via == "voice" and s.wav not in seen:
            seen.add(s.wav)
            steps.append(s)
    return steps


def spoken_words(text: str) -> int:
    """Words as said aloud: "40,000" is "forty thousand", "BHK" is "B H K"."""
    n = 0
    for tok in re.findall(r"[A-Za-z']+|\d[\d,]*", text):
        if re.fullmatch(r"\d{1,3}(,\d{3})+", tok):
            n += 2
        elif tok.isupper() and 2 <= len(tok) <= 4:
            n += len(tok)
        else:
            n += 1
    return n


class FormatError(ValueError):
    pass


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """(samples as float64, shape [n, channels]), sample rate. PCM16 only, any chunk layout."""
    b = path.read_bytes()
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        raise FormatError(f"{path.name}: not a WAV file")
    i, fmt, data = 12, None, None
    while i + 8 <= len(b):
        cid, size = b[i : i + 4], struct.unpack("<I", b[i + 4 : i + 8])[0]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack("<HHIIHH", b[i + 8 : i + 24])
            if tag == 0xFFFE and size >= 40:  # WAVE_FORMAT_EXTENSIBLE: the real tag is the GUID's
                tag = struct.unpack("<H", b[i + 32 : i + 34])[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            data = b[i + 8 : i + 8 + size]
        i += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise FormatError(f"{path.name}: WAV has no fmt or data chunk")
    tag, ch, rate, bits = fmt
    if tag != 1 or bits != 16:
        raise FormatError(f"{path.name}: {bits}-bit format {tag}; record as 16-bit PCM")
    if rate not in (48000, 16000):
        raise FormatError(
            f"{path.name}: {rate} Hz; record at 48 kHz (Windows Sound Recorder's default) or 16 kHz"
        )
    whole = len(data) // (2 * ch) * 2 * ch
    x = np.frombuffer(data[:whole], dtype="<i2").astype(np.float64)
    return x.reshape(-1, ch), rate


def to_mono(x: np.ndarray) -> np.ndarray:
    if x.shape[1] == 1:
        return x[:, 0]
    rms = np.sqrt((x**2).mean(axis=0)) + 1e-9
    if 20 * np.log10(rms.min() / rms.max()) < -20:
        return x[:, int(np.argmax(rms))]  # one dead channel: averaging would only halve the level
    return x.mean(axis=1)


def to_16k(x: np.ndarray, rate: int) -> np.ndarray:
    """48 kHz -> 16 kHz: windowed-sinc low-pass at 7.2 kHz (Blackman, 241 taps, ~74 dB stopband
    that starts below the new 8 kHz Nyquist), linear phase, then every third sample. The filter
    sums to 1, so speech below 7.2 kHz keeps its level."""
    if rate == RATE:
        return x
    taps = 241
    fc = 7200 / 48000
    n = np.arange(taps) - (taps - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * n) * np.blackman(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")[::3]


def bursts(y: np.ndarray) -> tuple[list[tuple[int, int, float]], int]:
    """Runs of loud 20 ms frames, as (first frame, last frame, peak dBFS), merged across short gaps."""
    frames = len(y) // FRAME
    f = y[: frames * FRAME].reshape(frames, FRAME)
    db = 20 * np.log10(np.sqrt((f**2).mean(axis=1)) / 32768 + 1e-12)
    thr = max(np.percentile(db, 10) + 12, np.percentile(db, 99) - 40)
    on, runs, i = db > thr, [], 0
    while i < frames:
        if on[i]:
            j = i
            while j + 1 < frames and on[j + 1]:
                j += 1
            runs.append([i, j])
            i = j + 1
        else:
            i += 1
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] - 1 < MERGE_FRAMES:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b, float(db[a : b + 1].max())) for a, b in merged], frames


@dataclass
class Result:
    wav: str
    say: str
    speech_s: float
    longest_pause_s: float
    peak_dbfs: float
    clipped: int
    click_removed: bool
    start: int  # sample range of the copy, in the 16 kHz signal
    end: int
    problems: list[str]


def examine(path: Path, say: str) -> tuple[Result, np.ndarray]:
    raw, rate = read_wav(path)
    clipped = int((np.abs(raw) >= 32767).sum())
    peak = 20 * np.log10(max(float(np.abs(raw).max()), 1.0) / 32768)
    y = to_16k(to_mono(raw), rate)
    segs, frames = bursts(y)
    problems: list[str] = []
    if not segs:
        return Result(path.name, say, 0.0, 0.0, peak, clipped, False, 0, 0, ["no speech found"]), y

    click = False
    a, b, _ = segs[-1]
    if (
        len(segs) > 1
        and frames - 1 - b <= CLICK_END_FRAMES
        and (b - a + 1) * FRAME <= CLICK_MAX_S * RATE
        and (a - segs[-2][1] - 1) * FRAME >= CLICK_GAP_S * RATE
    ):
        segs.pop()
        click = True
    loudest = max(p for _, _, p in segs)
    speech = [s for s in segs if s[2] >= loudest - FAINT_DB]
    first, last = speech[0][0], speech[-1][1]
    gaps = [(speech[k][0] - speech[k - 1][1] - 1) * FRAME / RATE for k in range(1, len(speech))]
    pause = max(gaps, default=0.0)
    speech_s = (last - first + 1) * FRAME / RATE

    if clipped:
        problems.append(f"clipped ({clipped} samples at full scale) - record a little quieter")
    if pause >= SPLIT_S:
        problems.append(f"a {pause:.2f} s pause will split the sentence in two - say it in one go")
    elif pause >= SPLIT_RISK_S:
        problems.append(
            f"a {pause:.2f} s pause is close to splitting the sentence - say it in one go"
        )
    words = spoken_words(say)
    if words == 1:
        if speech_s > YES_MAX_S:
            problems.append(f"{speech_s:.1f} s of speech for one word - is this the right file?")
    elif not RATE_WPS[0] <= words / speech_s <= RATE_WPS[1]:
        problems.append(
            f"{words / speech_s:.1f} words/s for this sentence - is this the right file?"
        )

    start = max(0, first * FRAME - int(LEAD_S * RATE))
    end = min(len(y), (last + 1) * FRAME + int(TAIL_S * RATE))
    return Result(path.name, say, speech_s, pause, peak, clipped, click, start, end, problems), y


def write_pcm16(path: Path, y: np.ndarray) -> None:
    pcm = np.clip(np.rint(y), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check-only" in args
    if check_only:
        args.remove("--check-only")
    out = DEFAULT_OUT
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print(
                "usage: prepare_recordings.py <folder> [--out DIR] [--check-only]", file=sys.stderr
            )
            return 2
        out = Path(args[i + 1])
        del args[i : i + 2]
    if len(args) != 1:
        print("usage: prepare_recordings.py <folder> [--out DIR] [--check-only]", file=sys.stderr)
        return 2
    src = Path(args[0])

    steps = load_plan_steps()
    missing = [s.wav for s in steps if not (src / s.wav).is_file()]
    if missing:
        print(f"missing from {src}: {', '.join(missing)}", file=sys.stderr)
        return 2

    checked = []
    try:
        for s in steps:
            checked.append(examine(src / s.wav, s.say))
    except FormatError as e:
        print(e, file=sys.stderr)
        return 2

    print(f"{'file':<16}{'speech':>8}{'longest pause':>15}{'peak':>9}{'Stop click':>12}  status")
    for r, _ in checked:
        status = "ok" if not r.problems else "PROBLEM: " + "; ".join(r.problems)
        print(
            f"{r.wav:<16}{r.speech_s:>7.2f}s{r.longest_pause_s:>14.2f}s{r.peak_dbfs:>7.1f}dB"
            f"{('removed' if r.click_removed else '-'):>12}  {status}"
        )

    if any(r.problems for r, _ in checked):
        print("\nNothing written: re-record the files marked PROBLEM, then run this again.")
        return 1
    if check_only:
        print("\nAll recordings pass. --check-only: nothing written.")
        return 0
    for r, y in checked:
        write_pcm16(out / r.wav, y[r.start : r.end])
    print(f"\nAll recordings pass. Wrote {len(checked)} files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
