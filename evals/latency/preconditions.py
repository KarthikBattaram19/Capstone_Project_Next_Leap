"""P1–P8 shown from evidence, not asserted (spec §5.2 preconditions; addendum Task 4.1).

`verify` is a pure function over three pieces of evidence — the settings in force, the
server's trace rows (`scout.platform.telemetry.Trace.to_json`, one per turn) and the
Railway service config — and returns one line per precondition:

    "P4 ✓ (n=38 traces)"
    "P4 ✗ trace 8f2a…: tts.first_byte after llm.last_token (1 of 38 traces)"
    "P2 cannot verify: <what the evidence is missing>"

The names checked are the ones the code emits today, found by reading it (2026-09-15),
not the ones the addendum guessed before the code existed:

- `tts.first_byte`, `llm.first_token`, `llm.last_token` are MARKS (`marks[].at_ms`), not
  spans. `tts.first_byte` is marked once per synthesised sentence (`SmallestTts.stream`),
  so the first one is the one that counts. `llm.*` come only from Job 2 (Anthropic);
  Job 1 is one non-streamed call (`external.gemini` or `external.groq` span), so a Type A
  trace never carries `llm.last_token`.
- `booking.writes` (confirm) and `booking.reschedule_writes` (reschedule) are spans with
  the calendar calls inside them as `external.google.insert` / `external.google.delete`.
  Only a booking made by voice is traced: the HTTP routes run outside any trace, so their
  spans are dropped (`telemetry.span` is a no-op with no current trace).
- Nothing emits a span for a Deepgram connection, and a trace row carries no session id.

A check the evidence cannot decide says "cannot verify" — never ✓.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable

OK, BAD = "✓", "✗"

TTS_FIRST_BYTE = "tts.first_byte"
LLM_FIRST_TOKEN = "llm.first_token"
LLM_LAST_TOKEN = "llm.last_token"
PARALLEL_WRITES = {
    # parent span -> the calendar calls that must run inside it at the same time (P6)
    "booking.writes": ("external.google.insert",),
    "booking.reschedule_writes": ("external.google.insert", "external.google.delete"),
}
ROUNDING_MS = 0.1  # to_json rounds every time to 0.1 ms


def _parse(trace_lines: Iterable[dict | str]) -> list[dict]:
    rows = []
    for ln in trace_lines:
        if isinstance(ln, str):
            if not ln.strip():
                continue
            ln = json.loads(ln)
        if "spans" in ln or "marks" in ln:  # a client row (L0…L8) is not a server trace
            rows.append(ln)
    return rows


def _tid(tr: dict) -> str:
    return f"{str(tr.get('turn_id', '?'))[:4]}…"


def _first_mark(tr: dict, name: str) -> float | None:
    ats = [m["at_ms"] for m in tr.get("marks", []) if m["name"] == name]
    return min(ats) if ats else None


def _setting(settings, name: str, want) -> str:
    if not hasattr(settings, name):
        return f"cannot verify: settings has no {name}"
    got = getattr(settings, name)
    if got == want:
        return f"{OK} ({name} = {got!r})"
    return f"{BAD} {name} = {got!r}, required {want!r}"


def _find_key(obj, key: str, path: str = "") -> list[tuple[str, object]]:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else k
            if k == key:
                found.append((here, v))
            found += _find_key(v, key, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _find_key(v, key, f"{path}[{i}]")
    return found


def check_p1(railway_service_json: dict | None) -> str:
    """Railway app sleeping off. Accepts railway.json (config as code) or any JSON export
    that carries `sleepApplication`; the key is searched for, not assumed at one path."""
    if railway_service_json is None:
        return "P1 cannot verify: no Railway service JSON given"
    found = _find_key(railway_service_json, "sleepApplication")
    if not found:
        return "P1 cannot verify: the Railway JSON has no sleepApplication key"
    on = [(p, v) for p, v in found if v is not False]
    if on:
        p, v = on[0]
        return f"P1 {BAD} {p} = {json.dumps(v)}"
    return f"P1 {OK} ({', '.join(p for p, _ in found)} = false)"


def check_p2() -> str:
    return (
        "P2 cannot verify: no span or mark records a Deepgram connection or a provider "
        "handshake, and trace rows carry no session id, so connections per session "
        "cannot be counted"
    )


def _ordered(
    traces: list[dict], first: str, then: str, *, turn_type: str | None
) -> tuple[int, list[str]]:
    """Traces carrying both marks, and a failure line for each where `first` is not earlier."""
    n, bad = 0, []
    for tr in traces:
        if turn_type is not None and tr.get("turn_type") != turn_type:
            continue
        a, b = _first_mark(tr, first), _first_mark(tr, then)
        if a is None or b is None:
            continue
        n += 1
        if not a < b:
            bad.append(f"trace {_tid(tr)}: {first} after {then}")
    return n, bad


def check_p4(traces: list[dict]) -> str:
    type_a_gap = (
        "Type A cannot verify: Job 1 is one non-streamed call, so no Type A trace has "
        f"{LLM_LAST_TOKEN}"
    )
    n, bad = _ordered(traces, TTS_FIRST_BYTE, LLM_LAST_TOKEN, turn_type=None)
    if n == 0:
        return (
            f"P4 cannot verify: no trace carries both {TTS_FIRST_BYTE} and {LLM_LAST_TOKEN}; "
            + type_a_gap
        )
    if bad:
        return f"P4 {BAD} {bad[0]} ({len(bad)} of {n} traces)"
    return f"P4 {OK} (n={n} traces with a streamed reply); {type_a_gap}"


def check_p5(traces: list[dict]) -> str:
    if not traces:
        return "P5 cannot verify: no traces given"
    for tr in traces:
        for item in [*tr.get("spans", []), *tr.get("marks", [])]:
            if "osm" in item["name"].lower():
                return f"P5 {BAD} trace {_tid(tr)}: {item['name']} at request time"
    return f"P5 {OK} (no OSM span in n={len(traces)} traces)"


def _parallel_failure(tr: dict, parent: dict, children: tuple[str, ...]) -> str | None:
    lo, hi = parent["start_ms"] - ROUNDING_MS, parent["end_ms"] + ROUNDING_MS
    calls = [
        s
        for s in tr.get("spans", [])
        if s["name"] in children and s["start_ms"] >= lo and s["end_ms"] <= hi
    ]
    name = parent["name"]
    if len(calls) < 2:
        return f"trace {_tid(tr)}: {name} holds {len(calls)} calendar call(s), expected ≥ 2"
    duration = parent["end_ms"] - parent["start_ms"]
    longest = max(s["end_ms"] - s["start_ms"] for s in calls)
    # Both rules. The duration rule alone passes a sequential pair when one call is much
    # shorter than the other; the overlap rule is the direct evidence that they ran at once.
    if max(s["start_ms"] for s in calls) >= min(s["end_ms"] for s in calls):
        return f"trace {_tid(tr)}: calendar calls inside {name} did not overlap (sequential)"
    if not duration < 2 * longest:
        return f"trace {_tid(tr)}: {name} {duration:.0f} ms ≥ 2× the longest call {longest:.0f} ms"
    return None


def check_p6(traces: list[dict]) -> str:
    n, bad = 0, []
    for tr in traces:
        for s in tr.get("spans", []):
            children = PARALLEL_WRITES.get(s["name"])
            if children is None:
                continue
            n += 1
            why = _parallel_failure(tr, s, children)
            if why:
                bad.append(why)
    if n == 0:
        return (
            "P6 cannot verify: no booking.writes or booking.reschedule_writes span in the "
            "traces (only voice bookings are traced; the HTTP booking routes run outside a trace)"
        )
    if bad:
        return f"P6 {BAD} {bad[0]} ({len(bad)} of {n} write groups)"
    return f"P6 {OK} (n={n} write groups)"


def check_p8(traces: list[dict]) -> str:
    n, bad = _ordered(traces, TTS_FIRST_BYTE, LLM_FIRST_TOKEN, turn_type="B")
    if n == 0:
        return (
            f"P8 cannot verify: no Type B trace carries both {TTS_FIRST_BYTE} and {LLM_FIRST_TOKEN}"
        )
    if bad:
        return f"P8 {BAD} {bad[0]} ({len(bad)} of {n} Type B traces)"
    return f"P8 {OK} (n={n} Type B traces)"


def verify(
    settings, trace_lines: Iterable[dict | str], railway_service_json: dict | None
) -> list[str]:
    traces = _parse(trace_lines)
    return [
        check_p1(railway_service_json),
        check_p2(),
        "P3 " + _setting(settings, "deepgram_endpointing_ms", 400),
        "P3b " + _setting(settings, "hold_extra_ms", 400),
        check_p4(traces),
        check_p5(traces),
        check_p6(traces),
        "P7 " + _setting(settings, "job2_effort", "low"),
        check_p8(traces),
    ]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Print the P1–P8 checklist from evidence.")
    ap.add_argument("traces", nargs="*", help="server trace JSONL (LATENCY_LOG_PATH)")
    ap.add_argument("--railway", help="railway.json or a Railway service JSON export")
    a = ap.parse_args()

    # P3, P3b and P7 are read from the settings THIS machine resolves (backend/.env, then the
    # environment). Production resolves its own from Railway's variables, so run this where
    # those are in force, or confirm no Railway variable overrides the three fields.
    from scout.config import Settings

    lines: list[str] = []
    for path in a.traces:
        with open(path, encoding="utf-8") as fh:
            lines += fh.readlines()
    railway = None
    if a.railway:
        with open(a.railway, encoding="utf-8") as fh:
            railway = json.load(fh)
    for line in verify(Settings(), lines, railway):
        print(line)
