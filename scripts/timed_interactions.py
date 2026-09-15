"""Task 4.1 driver: the 20 timed interactions against the deployed service (spec §5.2, §7.2).

    python scripts/timed_interactions.py --url wss://…/ws --label prod --dry-run
    python scripts/timed_interactions.py --url wss://…/ws --label prod --wav-dir data/raw/timed \
        --email <an inbox the reader credentials can read> --gmail-reader-credentials reader.json

Writes latency/timed-<label>.jsonl in the scorer's row shape (evals/latency/score.py):
8 Type A turns (L0 L1 L2 L4), 6 Type B turns (L0 L1 L3 L5), 3 bookings (L6), a reschedule
and a cancel (L7) and one PDF delivery (L8). `--cold-start` runs only the first Type A
turn and flags its row `cold_start: true`, which the scorer reports apart and never scores.

It extends scripts/latency_spike.py — the same paced 16 kHz PCM16 frames and the same stage
arithmetic — but holds ONE WebSocket per conversation, so the booking flow's pending state
carries from turn to turn and P2 (connection reuse) is in force, which the spike was not.

What a live run spends: three conversations, about 21 Job 1 calls (Gemini, from the
500-a-day allowance), 6 Job 2 calls, 3 bookings on the real calendars (all three are
cancelled again by the end) and 4 confirmation emails (3 bookings and the reschedule).

L8 needs a credential the service does not have. The service's Google token is scoped to
calendar + gmail.send (scripts/google_auth.py), and gmail.send cannot list messages, so the
poll uses a separate token with gmail.readonly on the inbox that receives --email, in the
JSON shape scripts/google_auth.py prints. The poll asks for `subject:<code> in:inbox`, not
the addendum's bare `subject:<code>`: on the sender's own account the Sent copy matches the
bare query the moment the send returns, which would time the send, not the delivery.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets


def _load_spike():
    # scripts/ is not a package; load the Gate L driver by path, as its own test does.
    spec = importlib.util.spec_from_file_location(
        "latency_spike", Path(__file__).with_name("latency_spike.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_spike = _load_spike()

CONTRACT_VERSION = "1"  # scout.contract.CONTRACT_VERSION
# Past 2× every L0–L7 target, so a turn that never answers is recorded as a 2× violation at
# this value rather than dropped as a missing number.
TURN_TIMEOUT_S = 45.0
SPEECH_START_GRACE_S = 8.0  # Speaker gives up on a first byte after 6 s (TTS_FIRST_BYTE_S)
SPEECH_MAX_S = 90.0  # a 90-word explanation is ~35 s of audio (spec §5.2)
SETTLE_S = 0.3  # live.py moves SPEAKING -> IDLE just after `audio_out end`
MAIL_TIMEOUT_S = 120.0  # 4× L8, so a late delivery is recorded as a value, not a gap
MAIL_POLL_S = 1.0  # L8's resolution; its target is 30 s
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"

Via = Literal["voice", "text", "reschedule", "cancel", "mail"]
Measure = Literal["A", "B", "L6", "L7", "L8"]


@dataclass(frozen=True)
class Step:
    conversation: int
    name: str
    via: Via
    say: str = ""
    wav: str | None = None  # a file under --wav-dir, the words of `say` spoken
    measure: Measure | None = None  # None: a step the conversation needs but nobody times
    expect: str = "any"  # a key of EXPECT: what the outcome must be for the flow to go on

    @property
    def id(self) -> str:
        return f"c{self.conversation}.{self.name}"


# One brief per conversation. Conversation 1's is the Gate L recording's words
# (data/raw/utterance_a_16k.wav), so that file can be reused as brief-1.wav. The localities
# exist in data/bundle/manifest.json (Koramangala 7, HSR Layout 10, BTM Layout 8 listings).
BRIEFS = {
    1: (
        "brief-1.wav",
        "I'm looking for a 2 BHK in Koramangala under 40,000 rupees, and I need parking",
    ),
    2: ("brief-2.wav", "Show me a 2 BHK in HSR Layout under 50,000"),
    3: ("brief-3.wav", "I need a 1 BHK in BTM Layout under 30,000"),
}


def build_plan(email: str) -> list[Step]:
    """readback → yes → why → area → book → slot → email → yes, three times, then HTTP.

    Timed: brief and readback-yes in every conversation plus a refinement in the first two
    (8 Type A), why and area in every one (6 Type B), every booking-yes (3 × L6), a
    reschedule in 1 and a cancel in 2 (L7), and conversation 3's PDF (L8). Book, slot and
    email are untimed: the email goes as a typed `text` frame because a spoken address is
    not reliably transcribed, and a typed turn has no end-of-speech to time from.
    """
    plan: list[Step] = []
    for c in (1, 2, 3):
        brief_wav, brief = BRIEFS[c]

        def voice(name, say, wav, measure=None, expect="any", c=c):
            return Step(c, name, "voice", say, wav, measure, expect)

        def typed(name, say, expect, c=c):
            return Step(c, name, "text", say, None, None, expect)

        plan += [
            voice("brief", brief, brief_wav, "A", "readback"),
            voice("readback-yes", "Yes", "yes.wav", "A", "shortlist"),
            voice("why", "Why did you pick the first one?", "why-first.wav", "B", "explanation"),
            voice("area", "What's the area like around the first one?", "area-first.wav", "B",
                  "explanation"),
            voice("book", "Book a visit to the first one", "book-first.wav", expect="slots"),
            typed("slot", "The first slot", "email"),
            typed("email", email, "email_confirm"),
            voice("booking-yes", "Yes", "yes.wav", "L6", "booked"),
        ]  # fmt: skip
        if c in (1, 2):
            plan.append(voice("refine", "What about under 60,000 instead?", "refine.wav", "A"))
        if c == 1:
            plan += [
                Step(c, "reschedule", "reschedule", measure="L7"),
                Step(c, "cleanup", "cancel"),
            ]
        elif c == 2:
            plan.append(Step(c, "cancel", "cancel", measure="L7"))
        else:
            # The PDF is timed in the conversation that is never rescheduled: a reschedule
            # mails a second PDF under the same subject, and the poll could find either.
            plan += [Step(c, "pdf", "mail", measure="L8"), Step(c, "cleanup", "cancel")]
    return plan


def measure_counts(plan: list[Step]) -> Counter:
    return Counter(s.measure for s in plan if s.measure)


# ---- frames (scout/contract/messages.py) and outcomes (scout/contract/outcome.py)


def hello_frame() -> str:
    return json.dumps({"type": "hello", "contract_version": CONTRACT_VERSION})  # HelloIn


def text_frame(text: str) -> str:
    return json.dumps({"type": "text", "text": text})  # TextIn, the typed fallback


def _vm(outcome: dict) -> dict:
    return outcome.get("view_model") or {}


def _needs(outcome: dict, fld: str) -> bool:
    return outcome.get("kind") == "needs_input" and outcome.get("field") == fld


# Field values are the ones the backend sets: NeedsInput.field in orchestrator.py
# ("constraints_readback") and voice_booking.py ("slot", "email", "email_confirm").
EXPECT: dict[str, Callable[[dict], bool]] = {
    "any": lambda o: True,
    "readback": lambda o: _needs(o, "constraints_readback"),
    "shortlist": lambda o: bool((_vm(o).get("shortlist") or {}).get("order")),
    "explanation": lambda o: (
        (o.get("kind") == "answered" and _vm(o).get("explanation") is not None)
        or o.get("kind") == "degraded"
    ),
    "slots": lambda o: _needs(o, "slot"),
    "email": lambda o: _needs(o, "email"),
    "email_confirm": lambda o: _needs(o, "email_confirm"),
    "booked": lambda o: o.get("kind") == "answered" and _vm(o).get("booking") is not None,
}


def outcome_matches(expect: str, outcome: dict | None) -> bool:
    return outcome is not None and EXPECT[expect](outcome)


# ---- the clock and the rows


@dataclass
class TurnClock:
    first_sent: float | None = None
    last_sent: float | None = None
    first_interim: float | None = None
    ack: float | None = None
    audio_started: bool = False
    first_audio: float | None = None
    outcome: float | None = None
    payload: dict | None = None  # OutcomeMsg.outcome
    speech_ended: float | None = None
    gave_up: float | None = None


def observe(clock: TurnClock, at: float, frame: str | bytes) -> None:
    """Fold one server frame into the clock, the way latency_spike.one_turn's reader does."""
    if isinstance(frame, bytes):
        if clock.audio_started and clock.first_audio is None:
            clock.first_audio = at
        return
    d = json.loads(frame)
    kind = d.get("type")
    if kind == "transcript" and not d.get("final") and clock.first_interim is None:
        clock.first_interim = at  # TranscriptMsg, final=False: L0
    elif kind == "ack" and clock.ack is None:
        clock.ack = at  # AckMsg: L1
    elif kind == "audio_out":  # AudioOutMsg
        if d.get("event") == "start":
            clock.audio_started = True
        elif d.get("event") in ("end", "stop") and clock.audio_started:
            clock.speech_ended = at
    elif kind == "outcome" and clock.outcome is None:
        clock.outcome = at  # OutcomeMsg: L4 / L5 / L6
        clock.payload = d.get("outcome")


def ms(later: float | None, earlier: float | None) -> float | None:
    return None if later is None or earlier is None else round((later - earlier) * 1000, 1)


def _tags(step: Step, label: str, cold_start: bool) -> dict:
    row = {"interaction": step.id, "label": label}
    if cold_start:
        row["cold_start"] = True
    return row


def _answered_or_gave_up(clock: TurnClock) -> tuple[float | None, bool]:
    if clock.outcome is not None:
        return clock.outcome, False
    return clock.gave_up, True


def turn_row(step: Step, clock: TurnClock, label: str, cold_start: bool = False) -> dict:
    """A Type A or B turn: L0 from the first frame sent, the rest from the last (spike rules)."""
    assert step.measure in ("A", "B"), step
    audio_key, outcome_key = ("L2", "L4") if step.measure == "A" else ("L3", "L5")
    done, timed_out = _answered_or_gave_up(clock)
    row = {
        "turn_type": step.measure,
        "L0": ms(clock.first_interim, clock.first_sent),
        "L1": ms(clock.ack, clock.last_sent),
        audio_key: ms(clock.first_audio, clock.last_sent),
        outcome_key: ms(done, clock.last_sent),
        **_tags(step, label, cold_start),
    }
    if timed_out:
        row["timed_out"] = True
    return row


def booking_row(step: Step, clock: TurnClock, label: str) -> dict:
    """L6: the booking-yes's last audio frame sent → the outcome carrying the booking.

    Spec §5.2 counts booking, cancel and reschedule as Type A, so L6 and L7 rows are Type A;
    L8 is too, as the tail of a Type A booking. A row carries only its own stage, so one
    booking turn is never scored twice.
    """
    done, timed_out = _answered_or_gave_up(clock)
    row = {"turn_type": "A", "L6": ms(done, clock.last_sent), **_tags(step, label, False)}
    if timed_out:
        row["timed_out"] = True
    return row


def http_row(step: Step, sent: float, answered: float, status: int, label: str) -> dict:
    """L7: the cancel or reschedule request sent → its HTTP response received."""
    return {
        "turn_type": "A",
        "L7": ms(answered, sent),
        "status": status,
        **_tags(step, label, False),
    }


def mail_row(step: Step, confirmed: float, found: float, delivered: bool, label: str) -> dict:
    """L8: the booking outcome received → the message listed in the inbox (or the give-up)."""
    return {
        "turn_type": "A",
        "L8": ms(found, confirmed),
        "delivered": delivered,
        **_tags(step, label, False),
    }


def row_measured(row: dict) -> bool:
    """A row that timed a completed interaction: answered, delivered, and a 200."""
    if row.get("timed_out") or row.get("delivered") is False or row.get("status", 200) != 200:
        return False
    return any(row.get(k) is not None for k in ("L4", "L5", "L6", "L7", "L8"))


def http_base(ws_url: str) -> str:
    """wss://host/ws -> https://host: the booking routes live beside the socket."""
    parts = urlsplit(ws_url)
    scheme = {"wss": "https", "ws": "http"}.get(parts.scheme, parts.scheme)
    path = parts.path.removesuffix("/ws")
    return urlunsplit((scheme, parts.netloc, path.rstrip("/"), "", ""))


def gmail_query(code: str) -> str:
    return f"subject:{code} in:inbox"


async def poll_until(
    fetch: Callable[[], Awaitable[bool]], timeout_s: float, poll_s: float
) -> tuple[float, bool]:
    """Call `fetch` every poll_s until it is true or timeout_s passes: (when, found)."""
    deadline = time.perf_counter() + timeout_s
    while True:
        if await fetch():
            return time.perf_counter(), True
        if time.perf_counter() >= deadline:
            return time.perf_counter(), False
        await asyncio.sleep(min(poll_s, max(0.0, deadline - time.perf_counter())))


def render_plan(
    plan: list[Step], wav_dir: Path | None, reader: Path | None, email: str | None
) -> list[str]:
    out = []
    for s in plan:
        src = ""
        if s.via == "voice":
            exists = wav_dir is not None and (wav_dir / s.wav).is_file()
            src = f"{s.wav}{'' if exists else ' (MISSING)'}"
        said = json.dumps(s.say, ensure_ascii=False) if s.say else ""
        out.append(
            f"{s.id:<17} {s.via:<10} {s.measure or '-':<3} {src:<28} {said} expect={s.expect}"
        )
    c = measure_counts(plan)
    total = sum(c.values())
    out.append(
        f"timed: A {c['A']} · B {c['B']} · L6 {c['L6']} · L7 {c['L7']} · L8 {c['L8']} = {total}"
    )
    out += [f"cannot run: {p}" for p in problems(plan, wav_dir, reader, email)]
    return out


def problems(
    plan: list[Step], wav_dir: Path | None, reader: Path | None, email: str | None
) -> list[str]:
    """Everything that would stop a live run part-way, found before a single call is made."""
    out = []
    if not email and any(s.name == "email" for s in plan):
        out.append("--email not given (the booking needs an address)")
    if wav_dir is None:
        out.append("--wav-dir not given")
    else:
        missing = sorted(
            {s.wav for s in plan if s.via == "voice" and not (wav_dir / s.wav).is_file()}
        )
        if missing:
            out.append(f"recordings missing from {wav_dir}: {', '.join(missing)}")
    if any(s.via == "mail" for s in plan) and (reader is None or not reader.is_file()):
        out.append(
            "--gmail-reader-credentials not given or not a file: L8 cannot be timed (the "
            "service token has gmail.send only, which cannot list messages)"
        )
    return out


# ---- the live parts (never exercised by the unit tests against anything but localhost)


class Conversation:
    """One /ws session held across turns."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.frames: asyncio.Queue[tuple[float, str | bytes]] = asyncio.Queue()
        self.session_id = ""
        self._reader: asyncio.Task | None = None

    @classmethod
    async def open(cls, url: str) -> Conversation:
        ws = await websockets.connect(url, max_size=None)
        await ws.send(hello_frame())
        hello = json.loads(await ws.recv())  # HelloOut
        assert hello["type"] == "hello", hello
        conv = cls(ws)
        conv.session_id = hello.get("session_id", "")
        conv._reader = asyncio.create_task(conv._read())
        return conv

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        await self.ws.close()

    async def _read(self) -> None:
        async for m in self.ws:
            await self.frames.put((time.perf_counter(), m))

    def _drain(self) -> None:
        while not self.frames.empty():
            self.frames.get_nowait()

    async def _until_outcome(self, clock: TurnClock) -> None:
        while clock.outcome is None:
            at, m = await self.frames.get()
            observe(clock, at, m)

    async def _until_quiet(self, clock: TurnClock) -> None:
        """Let the reply finish speaking: the next turn must neither barge in on it nor
        inherit its audio as its own first byte."""
        if clock.outcome is not None:
            start_by = clock.outcome + SPEECH_START_GRACE_S
            end_by = clock.outcome + SPEECH_MAX_S
            while clock.speech_ended is None:
                limit = end_by if clock.audio_started else start_by
                left = limit - time.perf_counter()
                if left <= 0:
                    break
                try:
                    at, m = await asyncio.wait_for(self.frames.get(), left)
                except TimeoutError:
                    break
                observe(clock, at, m)
        await asyncio.sleep(SETTLE_S)

    async def turn(self, step: Step, pcm: bytes | None, timeout_s: float = TURN_TIMEOUT_S):
        self._drain()
        clock = TurnClock()
        waiting = asyncio.create_task(self._until_outcome(clock))
        if pcm is None:
            clock.first_sent = clock.last_sent = time.perf_counter()
            await self.ws.send(text_frame(step.say))
            await asyncio.wait({waiting}, timeout=timeout_s)
        else:
            pacer = _spike.Pacer(self.ws)
            clock.first_sent = pacer.t_first_sent
            frame = _spike.FRAME_BYTES
            for i in range(0, len(pcm), frame):
                await pacer.send(pcm[i : i + frame])
            clock.last_sent = time.perf_counter()
            silence = b"\x00" * frame  # keep the stream alive so Deepgram can endpoint
            while not waiting.done() and time.perf_counter() - clock.last_sent < timeout_s:
                await pacer.send(silence)
        if not waiting.done():
            waiting.cancel()
            clock.gave_up = time.perf_counter()
        await asyncio.gather(waiting, return_exceptions=True)
        await self._until_quiet(clock)
        return clock


@dataclass
class BookingRef:
    code: str = ""
    listing_id: str = ""
    slot_start_ist: str = ""
    confirmed_at: float | None = None
    cancelled: bool = False


def gmail_reader(path: Path) -> Callable[[str], bool]:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    c = json.loads(path.read_text(encoding="utf-8"))  # scripts/google_auth.py's shape
    creds = Credentials(
        token=None,
        refresh_token=c["refresh_token"],
        client_id=c["client_id"],
        client_secret=c["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[GMAIL_READONLY],
    )
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def listed(query: str) -> bool:
        return bool(svc.users().messages().list(userId="me", q=query).execute().get("messages"))

    return listed


async def run(a: argparse.Namespace) -> int:
    plan = build_plan(a.email or "")
    if a.cold_start:
        plan = plan[:1]
    wav_dir = Path(a.wav_dir) if a.wav_dir else None
    reader = Path(a.gmail_reader_credentials) if a.gmail_reader_credentials else None
    blockers = problems(plan, wav_dir, reader, a.email)
    if blockers:
        for b in blockers:
            print("cannot run:", b, file=sys.stderr)
        return 2

    # A cold-start run gets its own file, so it never overwrites the warm run it precedes.
    out = Path("latency") / f"timed-{a.label}{'-cold' if a.cold_start else ''}.jsonl"
    out.parent.mkdir(exist_ok=True)
    rows: list[dict] = []
    listed = gmail_reader(reader) if reader and any(s.via == "mail" for s in plan) else None

    def write(fh, row: dict) -> None:
        rows.append(row)
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        print(row)

    async with httpx.AsyncClient(base_url=http_base(a.url), timeout=60) as client:
        if not a.cold_start:
            # The page has already spoken to the backend before anyone books, so the first
            # timed POST should not pay the TLS handshake alone (P2).
            await client.get("/health")
        with out.open("w", encoding="utf-8") as fh:
            for c in sorted({s.conversation for s in plan}):
                await _conversation(
                    a,
                    [s for s in plan if s.conversation == c],
                    wav_dir,
                    client,
                    listed,
                    lambda r: write(fh, r),
                )

    c = measure_counts(plan)
    measured = sum(1 for r in rows if row_measured(r))
    print(f"wrote {out}: {measured} of {sum(c.values())} planned interactions measured")
    return 0 if measured == sum(c.values()) else 1


async def _conversation(a, steps, wav_dir, client, listed, write) -> None:
    conv = await Conversation.open(a.url)
    booked = BookingRef()
    try:
        for step in steps:
            if step.via in ("voice", "text"):
                pcm = _spike.read_pcm16(wav_dir / step.wav) if step.via == "voice" else None
                clock = await conv.turn(step, pcm)
                matched = outcome_matches(step.expect, clock.payload)
                if step.measure in ("A", "B"):
                    # Any answer is a real turn of its type, whatever it said.
                    write(turn_row(step, clock, a.label, cold_start=a.cold_start))
                elif step.measure == "L6" and (matched or clock.outcome is None):
                    # Only a booking, or no answer at all, is an L6: a "slot taken" re-offer
                    # is a different stage and its time would flatter the row.
                    write(booking_row(step, clock, a.label))
                if not matched:
                    kind = (clock.payload or {}).get("kind", "no outcome")
                    print(f"{step.id}: expected {step.expect}, got {kind}; conversation stopped")
                    return
                if step.expect == "booked":
                    b = clock.payload["view_model"]["booking"]  # BookingVM
                    booked = BookingRef(
                        b["code"], b["listing_id"], b["slot"]["start_ist"], clock.outcome
                    )
            elif step.via == "reschedule":
                # SlotsRequest -> SlotsResponse, then RescheduleRequest -> BookingResponse
                r = await client.post("/bookings/slots", json={"listing_id": booked.listing_id})
                free = [s["start_ist"] for s in r.json().get("slots", [])]
                free = [s for s in free if s != booked.slot_start_ist]
                if not free:
                    print(f"{step.id}: no other free slot to move to; not timed")
                    continue
                body = {"code": booked.code, "slot_start_ist": free[0]}
                sent = time.perf_counter()
                resp = await client.post(f"/bookings/{booked.code}/reschedule", json=body)
                write(http_row(step, sent, time.perf_counter(), resp.status_code, a.label))
            elif step.via == "cancel":
                # The route takes no body; the frontend posts {} (frontend/src/lib/transport/http.ts).
                sent = time.perf_counter()
                resp = await client.post(f"/bookings/{booked.code}/cancel", json={})
                booked.cancelled = resp.status_code == 200
                if step.measure == "L7":
                    write(http_row(step, sent, time.perf_counter(), resp.status_code, a.label))
                else:
                    print(f"{step.id}: cancelled {booked.code} -> {resp.status_code}")
            elif step.via == "mail":
                q = gmail_query(booked.code)

                async def fetch(q=q) -> bool:
                    return await asyncio.to_thread(listed, q)

                found, delivered = await poll_until(fetch, MAIL_TIMEOUT_S, MAIL_POLL_S)
                write(mail_row(step, booked.confirmed_at, found, delivered, a.label))
    finally:
        await conv.close()
        if booked.code and not booked.cancelled:
            print(f"booking {booked.code} is still on both calendars; cancel it by code")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Task 4.1: the 20 timed interactions.")
    ap.add_argument("--url", required=True, help="the deployed socket, wss://…/ws")
    ap.add_argument("--label", required=True, help="output latency/timed-<label>.jsonl")
    ap.add_argument("--wav-dir", help="16 kHz mono PCM16 recordings named as in --dry-run")
    ap.add_argument("--email", help="where the confirmations go; its inbox is polled for L8")
    ap.add_argument("--gmail-reader-credentials", help="gmail.readonly token JSON for that inbox")
    ap.add_argument("--cold-start", action="store_true", help="one Type A turn, flagged cold")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; connect to nothing")
    a = ap.parse_args(argv)
    if a.dry_run:
        plan = build_plan(a.email or "<--email>")
        if a.cold_start:
            plan = plan[:1]
        reader = Path(a.gmail_reader_credentials) if a.gmail_reader_credentials else None
        wav_dir = Path(a.wav_dir) if a.wav_dir else None
        print(f"plan against {a.url} (http {http_base(a.url)}), label {a.label}; nothing sent")
        print("\n".join(render_plan(plan, wav_dir, reader, a.email)))
        return 0
    return asyncio.run(run(a))


if __name__ == "__main__":
    sys.exit(main())
