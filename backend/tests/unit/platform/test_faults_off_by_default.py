"""Fault injection is a door that must not exist in a normal deploy (Task 4.2).

POST /admin/fault makes providers fail on purpose. Unless FAULT_INJECTION is exactly "1"
the route is not registered at all and every provider wrapper's `faults.active` check
answers None; with it on, the route still answers only to the operator token.
"""

from typing import get_args

import pytest
from fastapi.testclient import TestClient

from scout.config import Settings
from scout.main import create_app
from scout.platform import faults

PROVIDERS = get_args(faults.Provider)


@pytest.fixture(autouse=True)
def _switch_off_afterwards():
    yield
    faults.configure(False)  # module state: never leak an enabled switch into another test


def _app(bundle_dir: str, **kw):
    return create_app(
        Settings(
            _env_file=None,
            cors_allowed_origins="http://localhost:3000",
            bundle_dir=bundle_dir,
            **kw,
        )
    )


def test_every_provider_wrapper_is_covered_by_the_switch():
    # Job 1 runs on Gemini (Settings.job1_provider); Groq stays the fallback.
    assert set(PROVIDERS) == {
        "deepgram",
        "gemini",
        "groq",
        "anthropic",
        "smallest",
        "calendar",
        "gmail",
    }
    assert set(faults.MODES) == set(PROVIDERS)


def test_the_route_is_absent_when_the_env_var_is_unset(bundle_min, monkeypatch):
    monkeypatch.delenv("FAULT_INJECTION", raising=False)
    c = TestClient(_app(bundle_min, operator_token="tok"))
    r = c.post(
        "/admin/fault",
        json={"provider": "groq", "mode": "down", "turns": 1},
        headers={"x-operator-token": "tok"},
    )
    assert r.status_code in (404, 405)


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on"])
def test_only_exactly_1_registers_the_route(bundle_min, monkeypatch, value):
    monkeypatch.setenv("FAULT_INJECTION", value)
    c = TestClient(_app(bundle_min, operator_token="tok"))
    r = c.post(
        "/admin/fault",
        json={"provider": "groq", "mode": "down", "turns": 1},
        headers={"x-operator-token": "tok"},
    )
    assert r.status_code in (404, 405)


def test_active_is_none_for_every_provider_when_unset(bundle_min, monkeypatch):
    monkeypatch.delenv("FAULT_INJECTION", raising=False)
    # Even a fault left over from an earlier app is gone once an app boots with it off.
    faults.configure(True)
    faults.set_fault("anthropic", "down", 5)
    _app(bundle_min)
    assert [faults.active(p) for p in PROVIDERS] == [None] * len(PROVIDERS)
    with pytest.raises(RuntimeError):
        faults.set_fault("groq", "down", 1)
    assert faults.active("groq") is None


def test_the_env_var_is_read_through_settings(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION", "1")
    assert faults.enabled_by(Settings(_env_file=None))
    monkeypatch.delenv("FAULT_INJECTION")
    assert not faults.enabled_by(Settings(_env_file=None))


# ---- with the switch on


def _on(bundle_min, monkeypatch, token="tok") -> TestClient:
    monkeypatch.setenv("FAULT_INJECTION", "1")
    return TestClient(_app(bundle_min, operator_token=token))


BODY = {"provider": "gemini", "mode": "429", "turns": 1}


def test_the_route_requires_the_operator_token(bundle_min, monkeypatch):
    c = _on(bundle_min, monkeypatch)
    assert c.post("/admin/fault", json=BODY).status_code == 401
    assert c.post("/admin/fault", json=BODY, headers={"x-operator-token": "no"}).status_code == 401
    assert faults.active("gemini") is None  # a refused request set nothing
    ok = c.post("/admin/fault", json=BODY, headers={"x-operator-token": "tok"})
    assert ok.status_code == 200 and ok.json() == BODY


def test_an_unset_operator_token_refuses_rather_than_matching_an_empty_header(
    bundle_min, monkeypatch
):
    c = _on(bundle_min, monkeypatch, token="")
    assert c.post("/admin/fault", json=BODY).status_code == 401
    assert c.post("/admin/fault", json=BODY, headers={"x-operator-token": ""}).status_code == 401
    assert faults.active("gemini") is None


def test_a_fault_fires_for_n_turns_then_clears(bundle_min, monkeypatch):
    c = _on(bundle_min, monkeypatch)
    r = c.post(
        "/admin/fault",
        json={"provider": "calendar", "mode": "timeout", "turns": 3},
        headers={"x-operator-token": "tok"},
    )
    assert r.status_code == 200
    assert [faults.active("calendar") for _ in range(4)] == ["timeout"] * 3 + [None]
    assert faults.active("gmail") is None  # one provider's fault is not another's


def test_turns_zero_clears_a_fault(bundle_min, monkeypatch):
    c = _on(bundle_min, monkeypatch)
    h = {"x-operator-token": "tok"}
    c.post("/admin/fault", json={"provider": "smallest", "mode": "down", "turns": 9}, headers=h)
    c.post("/admin/fault", json={"provider": "smallest", "mode": "down", "turns": 0}, headers=h)
    assert faults.active("smallest") is None


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "smallest", "mode": "schema_violation", "turns": 1},
        {"provider": "deepgram", "mode": "auth", "turns": 1},
        {"provider": "groq", "mode": "auth", "turns": 1},
        {"provider": "openai", "mode": "down", "turns": 1},
        {"provider": "groq", "mode": "slow", "turns": 1},
        {"provider": "groq", "mode": "down", "turns": -1},
    ],
)
def test_a_failure_the_provider_cannot_have_is_refused(bundle_min, monkeypatch, body):
    c = _on(bundle_min, monkeypatch)
    r = c.post("/admin/fault", json=body, headers={"x-operator-token": "tok"})
    assert r.status_code == 422
    assert [faults.active(p) for p in PROVIDERS] == [None] * len(PROVIDERS)
