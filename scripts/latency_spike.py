"""Gate L driver. Replays recorded utterances against the deployed /ws and times each stage."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

import websockets

FRAME_MS = 20


async def one_turn(url: str, wav: Path, turn_type: str) -> dict:
    with wave.open(str(wav), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, (
            "need 16 kHz mono PCM16"
        )
        pcm = w.readframes(w.getnframes())

    frame = 16000 * 2 * FRAME_MS // 1000  # 640 bytes
    t: dict[str, float | None] = {
        "first_interim": None,
        "ack": None,
        "first_audio": None,
        "outcome": None,
    }

    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "contract_version": "1"}))
        assert json.loads(await ws.recv())["type"] == "hello"

        async def reader() -> None:
            audio_started = False
            async for m in ws:
                now = time.perf_counter()
                if isinstance(m, bytes):
                    if audio_started and t["first_audio"] is None:
                        t["first_audio"] = now
                    continue
                d = json.loads(m)
                if d["type"] == "transcript" and not d["final"] and t["first_interim"] is None:
                    t["first_interim"] = now
                elif d["type"] == "ack":
                    t["ack"] = now
                elif d["type"] == "audio_out" and d["event"] == "start":
                    audio_started = True
                elif d["type"] == "outcome":
                    t["outcome"] = now
                    return

        rd = asyncio.create_task(reader())
        t_first_sent = time.perf_counter()
        for i in range(0, len(pcm), frame):
            await ws.send(pcm[i : i + frame])
            await asyncio.sleep(FRAME_MS / 1000)  # replay at real time
        t_last_sent = time.perf_counter()

        # Keep the stream alive with silence so Deepgram can endpoint.
        silence = b"\x00" * frame
        while not rd.done():
            await ws.send(silence)
            await asyncio.sleep(FRAME_MS / 1000)
            if time.perf_counter() - t_last_sent > 20:
                rd.cancel()
                break

    def ms(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else round((a - b) * 1000, 1)

    return {
        "turn_type": turn_type,
        "L0": ms(t["first_interim"], t_first_sent),
        "L1": ms(t["ack"], t_last_sent),
        ("L2" if turn_type == "A" else "L3"): ms(t["first_audio"], t_last_sent),
        ("L4" if turn_type == "A" else "L5"): ms(t["outcome"], t_last_sent),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--wav-a", required=True, help="a Type A utterance, 16 kHz mono PCM16")
    ap.add_argument("--wav-b", required=True, help="a Type B utterance (contains 'why')")
    ap.add_argument("--runs", type=int, default=25)
    ap.add_argument("--label", required=True, help="e.g. us-west or singapore")
    a = ap.parse_args()

    out = Path("latency") / f"spike-{a.label}.jsonl"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for i in range(a.runs):
            for tt, wav in (("A", a.wav_a), ("B", a.wav_b)):
                row = await one_turn(a.url, Path(wav), tt)
                row["run"] = i
                f.write(json.dumps(row) + "\n")
                print(row)
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
