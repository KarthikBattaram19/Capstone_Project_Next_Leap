"""Booking by voice over the fake calendar (Task 3.4): the same BookingService the routes use."""

import asyncio
from datetime import UTC, datetime

import pytest

from scout.api.http import NOT_FOUND_TELL
from scout.booking.reconcile import ReconcileQueue
from scout.booking.service import BookingService
from scout.config import Settings
from scout.contract.outcome import Answered, NeedsInput
from scout.conversation.job1 import Job1Result
from scout.conversation.orchestrator import NullSpeaker, TurnOrchestrator
from scout.conversation.session import SessionManager
from scout.conversation.speaker import split_sentences
from scout.conversation.voice_booking import VoiceBookingFlow, spell
from scout.domain.shortlist import Shortlist, ShortlistEntry
from scout.engines.availability import AvailabilityRegister
from scout.engines.slots import SlotService
from scout.platform.artefacts import ArtefactStore
from tests.unit.booking.test_service import FakeCal

NOW = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)  # 09:00 IST Tuesday
ORDER = ["kor-001", "kor-002", "hsr-001"]  # tests/fixtures/bundle_min/listings.json
SECOND = ORDER[1]


class ScriptedJob1:
    def __init__(self, results):
        self.results = list(results)

    async def extract(self, text, current):
        return self.results.pop(0)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, booking):
        self.sent.append(booking)
        return "sent"


def j1(intent="set_preferences", reference=None, email=None, code=None, slot_choice=None):
    return Job1Result(
        intent=intent,
        edits=[],
        ambiguities=[],
        reference=reference,
        email=email,
        code=code,
        slot_choice=slot_choice,
    )


@pytest.fixture
def make(bundle_min):
    def build(results):
        store = ArtefactStore.load(bundle_min)
        settings = Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_min
        )
        orch = TurnOrchestrator(
            store,
            settings,
            job1=ScriptedJob1(results),
            job2=None,
            availability=AvailabilityRegister(store),
            speaker_factory=lambda: NullSpeaker(),
        )
        cal = FakeCal()
        sender = FakeSender()
        orch.booking_flow = VoiceBookingFlow(
            BookingService(
                cal, SlotService(), orch.availability, ReconcileQueue(cal), now=lambda: NOW
            ),
            orch.vm,
            sender,
            orch._view,
        )
        s = SessionManager(60).create()
        # What the renter last heard: a shortlist over the fixture bundle, ranks from 1.
        s.shortlist = Shortlist(
            matched=tuple(ShortlistEntry(lid, i + 1) for i, lid in enumerate(ORDER))
        )
        s.last_read_order = s.shortlist.order
        return orch, s, cal, sender

    return build


BOOK_SCRIPT = [
    j1(intent="book", reference=2),
    j1(slot_choice=1),
    j1(intent="provide_email", email="karthik@example.com"),
    j1(intent="confirm_yes"),
]


async def _drive_to_email_confirm(orch, s):
    o1 = await orch.handle_text(s, "book the second one")
    assert isinstance(o1, NeedsInput) and o1.field == "slot"
    assert len(o1.options) == 3
    assert all(opt in o1.spoken for opt in o1.options)

    o2 = await orch.handle_text(s, "the first one")
    assert isinstance(o2, NeedsInput) and o2.field == "email"
    assert "email" in o2.spoken

    o3 = await orch.handle_text(s, "karthik at example dot com")
    assert isinstance(o3, NeedsInput) and o3.field == "email_confirm"
    assert "k-a-r-t-h-i-k at e-x-a-m-p-l-e dot c-o-m" in o3.spoken
    return o1, o2, o3


def test_spell_reads_every_character():
    assert spell("karthik@example.com") == "k-a-r-t-h-i-k at e-x-a-m-p-l-e dot c-o-m"
    assert spell("a.b@x.co.in") == "a-.-b at x dot c-o dot i-n"


async def test_book_by_voice_offers_slots_reads_the_email_back_and_speaks_the_code(make):
    orch, s, cal, sender = make(BOOK_SCRIPT)
    o1, o2, o3 = await _drive_to_email_confirm(orch, s)
    for o in (o1, o2, o3):
        assert len(split_sentences(o.spoken)) <= 3

    o4 = await orch.handle_text(s, "yes")
    assert isinstance(o4, Answered)
    code = o4.view_model.booking.code
    assert len(code) == 6
    assert " ".join(code) in o4.spoken
    assert o4.view_model.booking.listing_id == SECOND
    assert len(split_sentences(o4.spoken)) <= 3
    assert s.pending is None and s.email == "karthik@example.com"
    assert {c for c, *_ in cal.events.values()} == {"T", "O"}

    await asyncio.sleep(0)  # the PDF + email task runs off the interactive path (L8)
    assert [b.code for b in sender.sent] == [code]
    assert sender.sent[0].pdf_status == "sent"


async def test_withdrawn_between_readback_and_confirm_removes_it_and_rereads(make):
    orch, s, cal, sender = make(BOOK_SCRIPT)
    await _drive_to_email_confirm(orch, s)
    orch.availability.set(SECOND, False)

    o4 = await orch.handle_text(s, "yes")
    assert isinstance(o4, Answered)
    assert o4.view_model.booking is None
    assert any("removed" in n for n in o4.view_model.notices)
    assert SECOND not in o4.view_model.shortlist.order
    assert o4.view_model.shortlist.order == ["kor-001", "hsr-001"]
    assert s.last_read_order == ["kor-001", "hsr-001"]
    assert [e.rank for e in s.shortlist.matched] == [1, 2]
    assert "What remains" in o4.spoken
    assert len(split_sentences(o4.spoken)) <= 3
    assert cal.events == {} and sender.sent == []


async def test_cancel_with_an_unknown_code_gets_the_shared_not_found_line(make):
    orch, s, _, _ = make([j1(intent="cancel", code="ZZZZZZ")])
    o = await orch.handle_text(s, "cancel my visit, code ZZZZZZ")
    assert isinstance(o, Answered)
    assert o.spoken == NOT_FOUND_TELL


async def test_cancel_by_voice_reads_the_visit_back_and_needs_a_yes(make):
    orch, s, cal, _ = make(BOOK_SCRIPT + [j1(intent="cancel"), j1(intent="confirm_yes")])
    await _drive_to_email_confirm(orch, s)
    code = (await orch.handle_text(s, "yes")).view_model.booking.code
    assert cal.events

    orch.job1.results[0] = j1(intent="cancel", code=" ".join(code).lower())
    o = await orch.handle_text(s, "cancel it")
    assert isinstance(o, NeedsInput) and o.field == "cancel_confirm"
    assert "Koramangala" in o.spoken and "Cancel it?" in o.spoken

    o2 = await orch.handle_text(s, "yes")
    assert isinstance(o2, Answered)
    assert o2.spoken.startswith("Cancelled")
    assert o2.view_model.booking is None
    assert cal.events == {}


async def test_reschedule_by_voice_keeps_the_code_and_resends_the_pdf(make):
    orch, s, _cal, sender = make(
        BOOK_SCRIPT
        + [j1(intent="reschedule"), j1(slot_choice=2), j1(intent="reschedule"), j1(slot_choice=2)]
    )
    await _drive_to_email_confirm(orch, s)
    code = (await orch.handle_text(s, "yes")).view_model.booking.code
    await asyncio.sleep(0)

    orch.job1.results[0] = j1(intent="reschedule", code=code)
    o = await orch.handle_text(s, "move my visit")
    assert isinstance(o, NeedsInput) and o.field == "slot"
    assert s.reschedule_code == code

    o2 = await orch.handle_text(s, "the second one")
    assert isinstance(o2, Answered)
    assert o2.view_model.booking.code == code
    assert " ".join(code) in o2.spoken and "Rescheduled" in o2.spoken
    assert s.reschedule_code is None and s.pending is None
    assert len(split_sentences(o2.spoken)) <= 3
    await asyncio.sleep(0)
    assert [b.code for b in sender.sent] == [code, code]

    # A second reschedule to the slot it already holds changes nothing (§6.49).
    orch.job1.results[0] = j1(intent="reschedule", code=code)
    await orch.handle_text(s, "move it again")
    o3 = await orch.handle_text(s, "the second one again")
    assert isinstance(o3, Answered)
    assert "nothing" in o3.spoken.lower()
    assert s.reschedule_code is None


async def test_an_abandoned_reschedule_does_not_hijack_the_next_booking(make):
    orch, s, _cal, _sender = make([j1(intent="book", reference=1), j1(slot_choice=1)])
    # A reschedule was started, its slot prompt was abandoned (pending cleared by a later
    # turn), and the code it left behind must not turn the next booking into a move.
    s.reschedule_code = "AB12CD"
    o1 = await orch.handle_text(s, "book the first one")
    assert isinstance(o1, NeedsInput) and o1.field == "slot"
    assert s.reschedule_code is None
    o2 = await orch.handle_text(s, "the first one")
    assert isinstance(o2, NeedsInput) and o2.field == "email"  # a booking, not a move
