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


@pytest.mark.parametrize(
    "said",
    [
        "Okay. I'm ending the conversation here.",
        "Okay, that's all, thank you.",
        "Stop.",
        "Forget it.",
    ],
)
async def test_a_cancel_without_a_cancel_word_or_a_code_is_not_a_cancel(make, said):
    """A5, production 2026-09-17: "Okay. I'm ending the conversation here." was read as a
    cancel and she asked for the six-character code. A booking stays booked."""
    orch, s, cal, _ = make(BOOK_SCRIPT + [j1(intent="cancel")])
    await _drive_to_email_confirm(orch, s)
    await orch.handle_text(s, "yes")
    events = dict(cal.events)

    o = await orch.handle_text(s, said)

    assert "code" not in o.spoken.lower()
    assert not (isinstance(o, NeedsInput) and o.field in ("code", "cancel_confirm"))
    assert cal.events == events
    assert s.pending is None


@pytest.mark.parametrize(
    "said",
    [
        "cancel my visit",
        "I want to cancel the booking",
        "please call off the appointment",
        "Cancel my code.",
    ],
)
async def test_a_cancel_word_with_a_visit_word_still_asks_for_the_code(make, said):
    orch, s, _, _ = make([j1(intent="cancel")])
    o = await orch.handle_text(s, said)
    assert isinstance(o, NeedsInput) and o.field == "code"


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


# Production, 2026-09-17: the renter said an offered slot back as a time, the words the slot
# chips also send, and Job 1, which is not told a slot choice is pending, called it a
# reschedule with no code. "What's the six-character confirmation code?" followed.
@pytest.mark.parametrize("misread", ["reschedule", "cancel", "set_preferences"])
@pytest.mark.parametrize(
    "said",
    [
        "{offered}",  # the chip's own text
        "{offered}.",
        "11 am",
        "11 a.m. please",
        "eleven AM",
        "the one at 11",
        "11:00",
        "Tuesday at 11 o'clock",
        "1st September, 11 am",
    ],
)
async def test_a_spoken_slot_time_picks_that_slot_whatever_job1_made_of_it(make, misread, said):
    orch, s, _cal, _sender = make([j1(intent="book", reference=2), j1(intent=misread)])
    o1 = await orch.handle_text(s, "book the second one")
    assert o1.options[1] == "Tuesday 1 September at 11 am"
    offered = s.pending.slots

    o2 = await orch.handle_text(s, said.format(offered=o1.options[1]))
    assert isinstance(o2, NeedsInput) and o2.field == "email"
    assert s.pending.slot == offered[1] and s.pending.listing_id == SECOND


@pytest.mark.parametrize("said", ["4 pm", "Wednesday at 11 am", "3rd September at 10 am"])
async def test_a_spoken_time_that_was_not_offered_re_offers_the_three(make, said):
    orch, s, _cal, _sender = make([j1(intent="book", reference=2), j1(intent="reschedule")])
    o1 = await orch.handle_text(s, "book the second one")
    offered = s.pending.slots

    o2 = await orch.handle_text(s, said)
    assert isinstance(o2, NeedsInput) and o2.field == "slot"
    assert o2.options == o1.options  # the chips come back with the question
    assert all(opt in o2.spoken for opt in o1.options)
    assert s.pending.slots == offered


async def test_a_spoken_time_completes_a_reschedule_too(make):
    orch, s, _cal, _sender = make(BOOK_SCRIPT + [j1(intent="reschedule"), j1(intent="cancel")])
    await _drive_to_email_confirm(orch, s)
    code = (await orch.handle_text(s, "yes")).view_model.booking.code
    await asyncio.sleep(0)

    orch.job1.results[0] = j1(intent="reschedule", code=code)
    o = await orch.handle_text(s, "move my visit")
    assert isinstance(o, NeedsInput) and o.field == "slot"
    new = s.pending.slots[2]

    o2 = await orch.handle_text(s, o.options[2])
    assert isinstance(o2, Answered) and "Rescheduled" in o2.spoken
    assert o2.view_model.booking.code == code
    assert o2.view_model.booking.slot.start_ist == new.start.isoformat()


def test_match_offered_reads_days_and_leaves_distances_and_budgets_alone():
    from datetime import timedelta

    from scout.conversation.voice_booking import match_offered
    from scout.engines.slots import IST, Slot

    today_11 = datetime(2026, 9, 1, 11, tzinfo=IST)  # NOW is Tuesday 1 September, 09:00 IST
    offered = [
        Slot(today_11, today_11 + timedelta(hours=1)),
        Slot(today_11 + timedelta(days=1), today_11 + timedelta(days=1, hours=1)),
    ]
    assert match_offered("tomorrow at 11", offered, NOW) == offered[1]
    assert match_offered("today, 11 am", offered, NOW) == offered[0]
    assert match_offered("11 am", offered, NOW) is False  # two days offer 11: say which
    assert match_offered("September 2nd at eleven a.m.", offered, NOW) == offered[1]
    for not_a_time in ("anything at 5 km from the metro", "at 40k please", "the first one", ""):
        assert match_offered(not_a_time, offered, NOW) is None


# --- B1 (voice fix batch 2026-09-17): the answer to "What's the code?" is read in code ---


async def _booked_code(orch, s):
    await _drive_to_email_confirm(orch, s)
    return (await orch.handle_text(s, "yes")).view_model.booking.code


@pytest.mark.parametrize("shape", ["{c}.", "{spaced}", "It's {c}", "the code is {c} please"])
async def test_a_code_said_after_we_asked_for_it_continues_the_cancel(make, shape):
    """Production 2026-09-17 16:45 IST: code question -> "9VR7JP." -> "I can only help in
    English". Job 1 is not asked: the code is read from the words."""
    orch, s, _cal, _ = make(BOOK_SCRIPT + [j1(intent="cancel")])
    code = await _booked_code(orch, s)
    o = await orch.handle_text(s, "cancel my visit")
    assert isinstance(o, NeedsInput) and o.field == "code"

    said = shape.format(c=code, spaced=" ".join(code))
    o2 = await orch.handle_text(s, said)

    assert isinstance(o2, NeedsInput) and o2.field == "cancel_confirm", o2
    assert "Cancel it?" in o2.spoken
    assert orch.job1.results == []


async def test_a_code_said_after_we_asked_for_it_continues_the_reschedule(make):
    orch, s, _cal, _ = make(BOOK_SCRIPT + [j1(intent="reschedule")])
    code = await _booked_code(orch, s)
    await orch.handle_text(s, "I want to move my visit")

    o = await orch.handle_text(s, f"{code}.")

    assert isinstance(o, NeedsInput) and o.field == "slot"
    assert s.reschedule_code == code


@pytest.mark.parametrize("said", ["I was saying 9BRJ or 7JP.", "9VR7", "9 V R 7 J P Q"])
async def test_code_like_words_that_do_not_make_six_ask_for_the_characters(make, said):
    orch, s, _cal, _ = make([j1(intent="cancel")])
    await orch.handle_text(s, "cancel my visit")

    o = await orch.handle_text(s, said)

    assert isinstance(o, NeedsInput) and o.field == "code"
    assert o.spoken == "Please say the six characters one at a time."
    assert "isn't covered" not in o.spoken and "English" not in o.spoken
    assert orch.job1.results == []


async def test_no_code_at_all_is_an_ordinary_sentence_and_drops_the_question(make):
    orch, s, _cal, _ = make([j1(intent="cancel"), j1(intent="goodbye")])
    await orch.handle_text(s, "cancel my visit")

    o = await orch.handle_text(s, "Okay, I don't have it, bye.")

    assert "bye" in o.spoken.lower()
    assert s.pending is None and orch.job1.results == []


async def test_a_slot_time_is_read_before_job1_so_an_unclear_reading_cannot_swallow_it(make):
    orch, s, _cal, _ = make([j1(intent="book", reference=2), j1(intent="unclear")])
    o1 = await orch.handle_text(s, "book the second one")

    o2 = await orch.handle_text(s, o1.options[1])

    assert isinstance(o2, NeedsInput) and o2.field == "email"
    assert orch.job1.results == [j1(intent="unclear")]


@pytest.mark.parametrize(
    "said",
    [
        "A 3 BHK in HSR Layout under 45,000",
        "Show me a 2BHK under 25,000 rupees instead",
        "Book the second one on 25 September at 11 AM",
        "Actually move it to 25 September at 2 PM",
        "Make it 1.5 lakh and 3 BHK",
    ],
)
async def test_a_new_request_after_the_code_question_is_not_read_as_a_code(make, said):
    """Batch review, 2026-09-17: the digits of an amount, a bedroom count, a date or a time
    are not characters of a code. "A 3 BHK in HSR Layout under 45,000" read as "345" and got
    "Please say the six characters one at a time." - and would again on every such sentence,
    because the question stays pending."""
    orch, s, _cal, _ = make([j1(intent="cancel"), j1(intent="goodbye")])
    await orch.handle_text(s, "cancel my visit")

    o = await orch.handle_text(s, said)

    assert o.spoken != "Please say the six characters one at a time."
    assert orch.job1.results == [], "Job 1 reads an ordinary sentence"
    assert s.pending is None
