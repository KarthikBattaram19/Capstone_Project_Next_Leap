import pytest
from fastapi.testclient import TestClient

from scout.api.ws import CLOSE_CONTRACT_MISMATCH
from scout.config import Settings
from scout.main import create_app


def app(bundle_dir: str):
    return create_app(
        Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_dir
        )
    )


def _close_info(payload, bundle_dir):
    """Send `payload` as the first frame and report how the server closed the socket."""
    with TestClient(app(bundle_dir)).websocket_connect("/ws") as ws:
        ws.send_json(payload)
        with pytest.raises(Exception) as e:
            ws.receive_json()
    # starlette 1.6.0's WebSocketDisconnect stringifies to "", so the close code and
    # reason must be read from the attributes, not from str(e.value).
    return getattr(e.value, "code", None), getattr(e.value, "reason", None)


def test_wrong_contract_version_closes_with_named_reason(bundle_min):
    code, reason = _close_info({"type": "hello", "contract_version": "0"}, bundle_min)
    assert code == CLOSE_CONTRACT_MISMATCH == 4400
    assert reason == "contract_version_mismatch"


def test_non_hello_first_frame_is_rejected(bundle_min):
    # Valid JSON but not a hello falls through to the same check, so it closes with
    # the same code and reason.
    code, reason = _close_info({"type": "audio"}, bundle_min)
    assert code == CLOSE_CONTRACT_MISMATCH
    assert reason == "contract_version_mismatch"


def test_the_right_hello_is_answered_and_the_socket_stays_open(bundle_min):
    # The negative cases above pass just as well against a socket that rejects
    # everything, so the accepting path needs its own case.
    with TestClient(app(bundle_min)).websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "contract_version": "1"})
        assert ws.receive_json() == {"type": "hello", "contract_version": "1"}
