"""D2 (2026-09-17): the renter taps Stop while she speaks; the page sends {"type": "stop"}."""

from fastapi.testclient import TestClient

from scout.config import Settings
from scout.main import create_app


class FakeHandler:
    """Stands in for LiveSession: records what the gateway asked of it."""

    def __init__(self, sink):
        self.sink = sink
        self.calls = []
        self.session = type("S", (), {"id": "sess-1"})()

    async def start(self):
        self.calls.append("start")

    async def audio(self, pcm):
        self.calls.append("audio")

    async def text(self, text):
        self.calls.append("text")
        await self.sink.transcript("typed", final=True)  # lets the test wait for the frame

    async def stop(self):
        self.calls.append("stop")

    async def close(self):
        self.calls.append("close")


def test_a_stop_frame_stops_the_reply(bundle_min):
    app = create_app(
        Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_min
        )
    )
    made = []

    def factory(settings, sink):
        made.append(FakeHandler(sink))
        return made[-1]

    app.state.session_factory = factory
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "contract_version": "1"})
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "stop"})
        ws.send_json({"type": "text", "text": "two BHK"})
        assert ws.receive_json()["type"] == "transcript"
        assert made[0].calls == ["start", "stop", "text"]
