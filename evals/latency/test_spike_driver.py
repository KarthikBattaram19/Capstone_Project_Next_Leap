"""The driver's arithmetic decides Gate L, so it is tested against a fake /ws.

No provider and no deployment involved: a local WebSocket server replays the exact
message sequence the real gateway sends, and the driver's row is checked.
"""

import asyncio
import importlib.util
import json
import wave
from pathlib import Path

import pytest
import websockets

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "latency_spike", REPO / "scripts" / "latency_spike.py"
)
latency_spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(latency_spike)


def _wav(path: Path, ms: int = 200) -> Path:
    """A NON-silent 16 kHz mono PCM16 clip. The driver pads with silence once the
    utterance ends, so a non-silent clip lets the fake gateway tell the two apart —
    which is what real endpointing keys off."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x11\x22" * (16000 * ms // 1000))
    return path


async def _fake_gateway(ws):
    """hello -> interim transcript -> ack -> audio start -> one chunk -> outcome."""
    hello = json.loads(await ws.recv())
    assert hello == {"type": "hello", "contract_version": "1"}
    await ws.send(json.dumps({"type": "hello", "contract_version": "1"}))

    sent_interim = False
    async for msg in ws:
        if not isinstance(msg, bytes):
            continue
        if not sent_interim:
            # An interim lands while audio is still arriving, as Deepgram's would.
            await ws.send(json.dumps({"type": "transcript", "text": "two bhk", "final": False}))
            sent_interim = True
            continue
        if any(msg):
            continue  # still the utterance; wait for the silence padding
        # Silence reached: endpoint and finish the turn, as the real gateway would.
        await ws.send(json.dumps({"type": "transcript", "text": "two bhk", "final": True}))
        await ws.send(json.dumps({"type": "ack", "text": "two bhk", "state": "processing"}))
        await ws.send(
            json.dumps(
                {"type": "audio_out", "event": "start", "sample_rate": 24000, "format": "pcm16"}
            )
        )
        await ws.send(b"\x00\x00" * 240)
        await ws.send(json.dumps({"type": "audio_out", "event": "end"}))
        await ws.send(json.dumps({"type": "outcome", "kind": "answered"}))
        return


@pytest.mark.parametrize(
    ("turn_type", "audio_key", "outcome_key"),
    [("A", "L2", "L4"), ("B", "L3", "L5")],
)
async def test_one_turn_reports_the_right_stages(tmp_path, turn_type, audio_key, outcome_key):
    wav = _wav(tmp_path / "u.wav")
    async with websockets.serve(_fake_gateway, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        row = await asyncio.wait_for(
            latency_spike.one_turn(f"ws://127.0.0.1:{port}", wav, turn_type), timeout=30
        )

    assert row["turn_type"] == turn_type
    # Type A reports L2/L4; Type B reports L3/L5. Using the wrong pair would score the
    # explanation budget against the shortlist target.
    assert audio_key in row and outcome_key in row
    assert ("L3" if turn_type == "A" else "L2") not in row

    # L0 is measured from the FIRST frame sent; the rest from the LAST.
    assert row["L0"] is not None and row["L0"] > 0
    for k in (audio_key, outcome_key):
        assert row[k] is not None, f"{k} was never measured"
    # Audio precedes the outcome in the sequence above, so the budget order must hold.
    assert row[audio_key] <= row[outcome_key]
