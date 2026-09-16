"""Booking service against an in-memory calendar (Task 3.3). No Google client is ever built."""

from datetime import UTC, datetime, timedelta

from scout.booking.reconcile import ReconcileQueue
from scout.booking.service import (
    ALPHABET,
    AlreadyStarted,
    Booked,
    BookingService,
    Cancelled,
    CodeGenerator,
    NoSlots,
    NotFound,
    SlotTaken,
    Unchanged,
    Withdrawn,
)
from scout.domain.booking import BookingState
from scout.engines.slots import SlotService
from scout.providers.google_calendar import CalendarError, EventRef

NOW = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)  # 09:00 IST Tuesday


class FakeCal:
    """In-memory stand-in for GoogleCalendarAdapter: two calendars, "T" and "O"."""

    def __init__(self, fail_owner=False):
        self.tenant_id, self.owner_id = "T", "O"
        self.busy, self.events, self.fail_owner = [], {}, fail_owner
        self._n = 0

    async def freebusy(self, cal, start, end):
        return list(self.busy)

    # Same parameter names as GoogleCalendarAdapter.insert: the reconcile queue re-plays a
    # queued payload with **kwargs, so a fake that named `description` differently would
    # pass here and fail nowhere else.
    async def insert(self, cal, summary, description, slot, *, code, listing_id, email):
        if cal == "O" and self.fail_owner:
            raise CalendarError("owner calendar down")
        self._n += 1
        eid = f"{cal}-{self._n}"
        self.events[eid] = (cal, slot, code, listing_id, email)
        return eid

    async def delete(self, cal, eid):
        self.events.pop(eid, None)

    async def find_by_code(self, code):
        return [
            EventRef(c, eid, s.start, s.end, lid, em)
            for eid, (c, s, cd, lid, em) in self.events.items()
            if cd == code
        ]


class Avail:
    def __init__(self):
        self.flags = {"a": True}

    def is_available(self, lid):
        return self.flags.get(lid, True)


def svc(cal=None, avail=None):
    return BookingService(
        cal or FakeCal(),
        SlotService(),
        avail or Avail(),
        ReconcileQueue(cal or FakeCal()),
        now=lambda: NOW,
    )


async def test_offer_returns_first_three_free_slots():
    slots = await svc().offer("a")
    assert len(slots) == 3 and slots[0].start.hour == 10


async def test_confirm_writes_both_and_issues_a_code():
    cal = FakeCal()
    s = svc(cal)
    slot = (await s.offer("a"))[0]
    r = await s.confirm("a", slot, "t@x")
    assert isinstance(r, Booked)
    assert len(r.booking.code) == 6
    assert r.booking.state is BookingState.BOOKED
    assert {c for c, *_ in cal.events.values()} == {"T", "O"}
    assert r.booking.calendar_complete


async def test_confirm_rechecks_availability_before_any_write():
    cal, av = FakeCal(), Avail()
    s = svc(cal, av)
    slot = (await s.offer("a"))[0]
    av.flags["a"] = False
    r = await s.confirm("a", slot, "t@x")
    assert isinstance(r, Withdrawn) and not cal.events


async def test_confirm_rechecks_freebusy_and_reoffers():
    cal = FakeCal()
    s = svc(cal)
    slot = (await s.offer("a"))[0]
    cal.busy.append((slot.start, slot.end))
    r = await s.confirm("a", slot, "t@x")
    assert isinstance(r, SlotTaken)
    assert r.alternatives and r.alternatives[0].start != slot.start
    assert not cal.events


async def test_half_landed_write_is_booked_and_queued_for_retry():
    cal = FakeCal(fail_owner=True)
    q = ReconcileQueue(cal)
    s = BookingService(cal, SlotService(), Avail(), q, now=lambda: NOW)
    slot = (await s.offer("a"))[0]
    r = await s.confirm("a", slot, "t@x")
    assert isinstance(r, Booked)
    assert r.booking.state is BookingState.BOOKED and not r.booking.calendar_complete
    assert q.pending_for(r.booking.code) == 1


async def test_unknown_and_cancelled_codes_are_indistinguishable():
    cal = FakeCal()
    s = svc(cal)
    slot = (await s.offer("a"))[0]
    b = (await s.confirm("a", slot, "t@x")).booking
    await s.cancel(b.code)
    assert isinstance(await s.cancel(b.code), NotFound)
    assert isinstance(await s.cancel("ZZZZZZ"), NotFound)
    assert type(await s.lookup(b.code)) is type(await s.lookup("ZZZZZZ"))


async def test_reschedule_keeps_code_and_same_slot_is_unchanged():
    cal = FakeCal()
    s = svc(cal)
    slots = await s.offer("a")
    b = (await s.confirm("a", slots[0], "t@x")).booking
    assert isinstance(await s.reschedule(b.code, slots[0]), Unchanged)
    r = await s.reschedule(b.code, slots[1])
    assert r.booking.code == b.code and r.booking.slot == slots[1]
    assert all(sl.start == slots[1].start for _, sl, *_ in cal.events.values())


async def test_reconcile_repairs_the_failed_half_once_and_never_twice():
    cal = FakeCal(fail_owner=True)
    q = ReconcileQueue(cal)
    s = BookingService(cal, SlotService(), Avail(), q, now=lambda: NOW)
    slot = (await s.offer("a"))[0]
    b = (await s.confirm("a", slot, "t@x")).booking
    await q.run_once()  # owner calendar still down: the job stays, one attempt recorded
    assert q.pending_for(b.code) == 1 and q.jobs[0].attempts == 1
    assert not (await s.lookup(b.code)).calendar_complete
    cal.fail_owner = False
    await q.run_once()
    assert q.pending_for(b.code) == 0
    assert {c for c, *_ in cal.events.values()} == {"T", "O"}
    assert (await s.lookup(b.code)).calendar_complete
    # A write that landed but whose response was lost: the code on the event is the
    # idempotency key, so replaying the job must not put a second visit on the calendar.
    q.enqueue(
        "insert",
        "O",
        b.code,
        {
            "summary": "Site visit — a",
            "description": f"Confirmation code {b.code}",
            "slot": slot,
            "code": b.code,
            "listing_id": "a",
            "email": "t@x",
        },
    )
    before = len(cal.events)
    await q.run_once()
    assert not q.jobs and len(cal.events) == before


async def test_cancel_drops_queued_repairs_so_no_half_lands_afterwards():
    # The owner insert fails, the booking stands with one repair queued; the renter then
    # cancels. The queue must forget that repair, or it re-creates the visit later.
    cal = FakeCal(fail_owner=True)
    q = ReconcileQueue(cal)
    s = BookingService(cal, SlotService(), Avail(), q, now=lambda: NOW)
    slot = (await s.offer("a"))[0]
    b = (await s.confirm("a", slot, "t@x")).booking
    assert q.pending_for(b.code) == 1
    cal.fail_owner = False  # the calendar comes back
    assert isinstance(await s.cancel(b.code), Cancelled)
    assert q.pending_for(b.code) == 0
    await q.run_once()
    assert not cal.events and await s.lookup(b.code) is None


# --- §6 walkthrough rows: guards that were read but not executed (Task 4.2) ---


async def test_cancel_and_reschedule_after_the_slot_started_are_both_refused():
    """Spec §6.10. The clock that decides this is IST (`engines/slots.py:51`), not the
    server's - so the test moves `now` past the slot rather than moving the slot."""
    cal = FakeCal()
    s = svc(cal)
    offered = await s.offer("a")
    slot = offered[0]
    code = (await s.confirm("a", slot, "t@x")).booking.code

    # The same calendar, read from a clock one minute after the visit began.
    started = BookingService(
        cal,
        SlotService(),
        Avail(),
        ReconcileQueue(cal),
        now=lambda: slot.start + timedelta(minutes=1),
    )
    assert isinstance(await started.cancel(code), AlreadyStarted)
    assert isinstance(await started.reschedule(code, offered[2]), AlreadyStarted)
    # Refused means nothing moved: both events are still there, on the original slot.
    assert len(cal.events) == 2
    assert all(s_.start == slot.start for _, s_, *_ in cal.events.values())


async def test_no_free_slot_in_the_window_is_NoSlots_not_an_empty_list():
    """Spec §6.40. An empty list would reach the renter as "pick one" from nothing, so the
    absence of slots has to be its own answer."""
    cal = FakeCal()
    start, end = SlotService().window(NOW)
    cal.busy = [(start, end)]  # the whole 7-day window is busy
    r = await svc(cal).offer("a")
    assert isinstance(r, NoSlots)
    assert not isinstance(r, list)


async def test_a_confirmation_code_collision_redraws_instead_of_overwriting():
    """Spec §6.44. `CodeGenerator.new` is driven directly: forcing a real collision through
    `confirm` would mean fixing `secrets.choice`, which would test the patch, not the guard."""
    drawn: list[str] = []

    async def exists(code: str) -> bool:
        drawn.append(code)
        return len(drawn) <= 2  # the first two draws are already live bookings

    code = await CodeGenerator.new(exists)

    assert len(drawn) == 3, "it must draw again on a collision, not reuse or overwrite"
    assert code == drawn[-1]
    assert len(code) == 6
    # The confusion-free alphabet: no 0/O or 1/I, which are misread when spoken aloud.
    assert set("".join(drawn)) <= set(ALPHABET)
    assert not set(ALPHABET) & set("01OI")
