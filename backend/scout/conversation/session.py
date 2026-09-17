"""In-memory, expiring, one lock per session. A refresh loses it; a second tab is a second one."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from scout.domain.constraints import ConstraintSet
from scout.domain.shortlist import Shortlist


@dataclass
class ConfirmConstraints:
    pass


@dataclass
class ConfirmHeard:
    """A transcript Deepgram was not confident about (spec §6.20). `text` is replayed as a
    fresh turn if the renter says yes, so a noisy utterance is confirmed, never guessed."""

    text: str


@dataclass
class ConfirmLocality:
    """A locality recognised inside a sentence that was not in English (spec §6.25). Nothing
    from that sentence is used until the renter says yes to the locality by name; `edits` are
    only its localities edits, never a budget or a bedroom count heard in another language."""

    edits: list  # list[ConstraintEdit]


@dataclass
class AwaitLocalityChoice:
    """ "Did you mean A, B or C?" was asked (spec §6.24). The answer is matched against
    `options` in code before Job 1, which would otherwise read "the 2nd one" or a name cold
    (B1, production 2026-09-17)."""

    options: list[str]
    heard: str


@dataclass
class AwaitCode:
    """ "What's the six-character confirmation code?" was asked for `action` ("cancel" or
    "reschedule"). The code is read from the words in code before Job 1 (B1)."""

    action: str


@dataclass
class AwaitSlotChoice:
    listing_id: str
    slots: list  # list[Slot] (Task 3.1)


@dataclass
class AwaitEmail:
    listing_id: str
    slot: object


@dataclass
class ConfirmEmail:
    listing_id: str
    slot: object
    email: str


@dataclass
class ConfirmCancel:
    code: str


PendingAction = (
    ConfirmConstraints
    | ConfirmHeard
    | ConfirmLocality
    | AwaitLocalityChoice
    | AwaitCode
    | AwaitSlotChoice
    | AwaitEmail
    | ConfirmEmail
    | ConfirmCancel
)


@dataclass
class Session:
    id: str
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    shortlist: Shortlist = field(default_factory=Shortlist)
    last_read_order: list[str] = field(default_factory=list)  # what the renter last HEARD (§6.30)
    clarifying_asked: int = 0
    audio_unlocked: bool = False
    pending: PendingAction | None = None
    email: str | None = None
    focus_listing_id: str | None = None
    reschedule_code: str | None = None
    # E2: "the listings don't state the kind of parking" is said once per conversation.
    parking_kind_explained: bool = False
    speaker_factory: Callable[[], object] | None = None  # set per live session (Task 2.10)
    speaker: object | None = None
    speaking: asyncio.Task | None = None
    job2_task: asyncio.Task | None = None
    # What the claim assembler bound and dropped over this session's lane B turns.
    # Per session means per eval case: a fresh case starts empty (Docs/JOB2_SCORES.md).
    job2_bound: int = 0
    job2_drops: dict[str, int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.last_seen = datetime.now(UTC)


class SessionManager:
    def __init__(self, ttl_s: int) -> None:
        self._ttl = timedelta(seconds=ttl_s)
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        s = Session(id=uuid.uuid4().hex[:16])
        self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def expire_idle(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        dead = [k for k, s in self._sessions.items() if now - s.last_seen > self._ttl]
        for k in dead:
            del self._sessions[k]
        return len(dead)
