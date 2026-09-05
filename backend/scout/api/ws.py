"""The mic WebSocket — one of the two doors into the backend (arch §6.4, §11.1)."""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from scout.contract import CONTRACT_VERSION

router = APIRouter()

CLOSE_CONTRACT_MISMATCH = 4400


class WsSink:
    """What a turn can send to the browser. The orchestrator (Task 2.10) talks only to this."""

    def __init__(self, ws: WebSocket, sample_rate: int) -> None:
        self._ws, self._rate = ws, sample_rate

    async def transcript(self, text: str, final: bool) -> None:
        await self._ws.send_json({"type": "transcript", "text": text, "final": final})

    async def ack(self, text: str) -> None:
        await self._ws.send_json({"type": "ack", "text": text, "state": "processing"})

    async def audio_start(self) -> None:
        await self._ws.send_json(
            {"type": "audio_out", "event": "start", "sample_rate": self._rate, "format": "pcm16"}
        )

    async def audio_chunk(self, pcm: bytes) -> None:
        await self._ws.send_bytes(pcm)

    async def audio_end(self) -> None:
        await self._ws.send_json({"type": "audio_out", "event": "end"})

    async def audio_stop(self) -> None:  # barge-in
        await self._ws.send_json({"type": "audio_out", "event": "stop"})

    async def outcome(self, payload: dict) -> None:
        await self._ws.send_json({"type": "outcome", **payload})


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    settings = ws.app.state.settings

    try:
        first = json.loads(await ws.receive_text())
    except Exception:  # noqa: BLE001 -- a bad first frame of ANY kind closes cleanly,
        # never leaks a traceback to the browser. Narrowing this would let some new
        # decode error escape the handshake.
        await ws.close(code=CLOSE_CONTRACT_MISMATCH, reason="hello_expected")
        return

    if first.get("type") != "hello" or first.get("contract_version") != CONTRACT_VERSION:
        await ws.close(code=CLOSE_CONTRACT_MISMATCH, reason="contract_version_mismatch")
        return

    await ws.send_json({"type": "hello", "contract_version": CONTRACT_VERSION})

    sink = WsSink(ws, settings.smallest_sample_rate)
    session_handler = ws.app.state.session_factory(settings, sink)  # stub now; orchestrator later
    await session_handler.start()

    try:
        while True:
            frame = await ws.receive()
            if frame.get("bytes") is not None:
                await session_handler.audio(frame["bytes"])
            elif frame.get("text") is not None:
                msg = json.loads(frame["text"])
                if msg.get("type") == "text":  # typed fallback (spec §6.13)
                    await session_handler.text(msg["text"])
            elif frame.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await session_handler.close()
