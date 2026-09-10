"""Slot arithmetic in IST, plain code; confirm-time re-checks; parallel writes (arch §10.2)."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from scout.booking.reconcile import ReconcileQueue
from scout.domain.booking import Booking, BookingState, Slot
from scout.engines.slots import SlotService
from scout.platform import telemetry

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I (spec §6.44)


class CodeGenerator:
    @staticmethod
    async def new(exists: Callable[[str], Awaitable[bool]]) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(6))
            if not await exists(code):
                return code
            # collision: draw again


@dataclass
class Booked:
    booking: Booking
    tell: str


@dataclass
class SlotTaken:
    alternatives: list[Slot]


@dataclass
class Withdrawn:
    listing_id: str


@dataclass
class NoSlots:
    next_available: Slot | None


@dataclass
class NotFound:
    pass


@dataclass
class AlreadyStarted:
    pass


@dataclass
class Unchanged:
    booking: Booking


@dataclass
class Cancelled:
    code: str


@dataclass
class Rescheduled:
    booking: Booking
    tell: str


class BookingService:
    def __init__(
        self,
        calendar,
        slots: SlotService,
        availability,
        reconcile: ReconcileQueue,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.cal, self.slots, self.avail, self.q, self.now = (
            calendar,
            slots,
            availability,
            reconcile,
            now,
        )

    async def _free(self) -> list[Slot]:
        start, end = self.slots.window(self.now())
        busy = await self.cal.freebusy(self.cal.owner_id, start, end)
        return self.slots.free_slots(busy, self.now())

    async def offer(self, listing_id: str) -> list[Slot] | NoSlots:
        free = await self._free()
        if not free:
            return NoSlots(next_available=None)  # spec §6.40 — never "pick one" from nothing
        return self.slots.first(free, 3)

    async def _exists(self, code: str) -> bool:
        return bool(await self.cal.find_by_code(code))

    async def confirm(
        self, listing_id: str, slot: Slot, email: str
    ) -> Booked | SlotTaken | Withdrawn:
        if not self.avail.is_available(listing_id):
            return Withdrawn(listing_id)  # §6.43 — the flag, never the source site
        free = await self._free()  # §6.41 — re-read at confirm, not trusted from offer
        if slot not in free:
            return SlotTaken(alternatives=self.slots.first(free, 3))
        code = await CodeGenerator.new(self._exists)
        booking = Booking(
            code=code,
            listing_id=listing_id,
            slot=slot,
            state=BookingState.CONFIRMING,
            email=email,
        )
        with telemetry.span("booking.writes"):
            results = await asyncio.gather(  # P6 — both writes at the same time
                self.cal.insert(
                    self.cal.tenant_id,
                    f"Site visit — {listing_id}",
                    f"Confirmation code {code}",
                    slot,
                    code=code,
                    listing_id=listing_id,
                    email=email,
                ),
                self.cal.insert(
                    self.cal.owner_id,
                    f"Tenant visit — {listing_id}",
                    f"Confirmation code {code}",
                    slot,
                    code=code,
                    listing_id=listing_id,
                    email=email,
                ),
                return_exceptions=True,
            )
        booking.tenant_event_id = results[0] if isinstance(results[0], str) else None
        booking.owner_event_id = results[1] if isinstance(results[1], str) else None
        for cal_id, res in ((self.cal.tenant_id, results[0]), (self.cal.owner_id, results[1])):
            if not isinstance(res, str):  # the write failed: repair it behind the scenes
                self.q.enqueue(
                    "insert",
                    cal_id,
                    code,
                    {
                        "summary": f"Site visit — {listing_id}",
                        "description": f"Confirmation code {code}",
                        "slot": slot,
                        "code": code,
                        "listing_id": listing_id,
                        "email": email,
                    },
                )
        booking.state = BookingState.BOOKED  # the renter's intended state is authoritative (§6.3)
        booking.calendar_complete = all(isinstance(r, str) for r in results)
        tell = f"Booked — your code is {' '.join(code)}."
        if not booking.calendar_complete:
            tell += (
                " The calendar is temporarily unreachable; "
                "I've recorded the visit and will sync it shortly."
            )
        return Booked(booking, tell)

    async def lookup(self, code: str) -> Booking | None:
        refs = await self.cal.find_by_code(code)
        if not refs:
            return None  # unknown == cancelled (§6.9, §6.45)
        r = refs[0]
        b = Booking(
            code=code,
            listing_id=r.listing_id,
            slot=Slot(r.start, r.end),
            state=BookingState.BOOKED,
            email=r.email,
            tenant_event_id=next(
                (x.event_id for x in refs if x.calendar_id == self.cal.tenant_id), None
            ),
            owner_event_id=next(
                (x.event_id for x in refs if x.calendar_id == self.cal.owner_id), None
            ),
        )
        b.calendar_complete = (
            b.tenant_event_id is not None
            and b.owner_event_id is not None
            and self.q.pending_for(code) == 0
        )
        return b

    async def _delete_both(self, b: Booking) -> None:
        pairs = [(self.cal.tenant_id, b.tenant_event_id), (self.cal.owner_id, b.owner_event_id)]
        results = await asyncio.gather(
            *(self.cal.delete(c, e) for c, e in pairs if e), return_exceptions=True
        )
        for (c, e), res in zip([p for p in pairs if p[1]], results, strict=True):
            if isinstance(res, Exception):
                self.q.enqueue("delete", c, b.code, {"event_id": e})

    async def cancel(self, code: str) -> Cancelled | NotFound | AlreadyStarted:
        b = await self.lookup(code)
        if b is None:
            return NotFound()
        if self.slots.has_started(b.slot, self.now()):
            return AlreadyStarted()
        self.q.drop(code)  # a queued repair must not re-create what is being cancelled
        await self._delete_both(b)
        return Cancelled(code)

    async def reschedule(
        self, code: str, slot: Slot
    ) -> Rescheduled | NotFound | AlreadyStarted | SlotTaken | Unchanged:
        b = await self.lookup(code)
        if b is None:
            return NotFound()
        if self.slots.has_started(b.slot, self.now()):
            return AlreadyStarted()
        if slot == b.slot:
            return Unchanged(b)  # §6.49 — nothing deleted, nothing recreated
        free = await self._free()
        if slot not in free:
            return SlotTaken(alternatives=self.slots.first(free, 3))
        self.q.drop(code)  # a queued insert for the OLD slot must not land after the move
        with telemetry.span("booking.reschedule_writes"):  # four calls, in parallel (L7)
            await asyncio.gather(
                self._delete_both(b), self._insert_both(b.listing_id, slot, code, b.email)
            )
        nb = await self.lookup(code)
        return Rescheduled(
            nb or Booking(code, b.listing_id, slot, BookingState.BOOKED, b.email),
            f"Rescheduled to {slot.spoken()} — same code, {' '.join(code)}.",
        )

    async def _insert_both(self, listing_id: str, slot: Slot, code: str, email: str) -> None:
        results = await asyncio.gather(
            self.cal.insert(
                self.cal.tenant_id,
                f"Site visit — {listing_id}",
                f"Confirmation code {code}",
                slot,
                code=code,
                listing_id=listing_id,
                email=email,
            ),
            self.cal.insert(
                self.cal.owner_id,
                f"Tenant visit — {listing_id}",
                f"Confirmation code {code}",
                slot,
                code=code,
                listing_id=listing_id,
                email=email,
            ),
            return_exceptions=True,
        )
        for cal_id, res in ((self.cal.tenant_id, results[0]), (self.cal.owner_id, results[1])):
            if not isinstance(res, str):
                self.q.enqueue(
                    "insert",
                    cal_id,
                    code,
                    {
                        "summary": f"Site visit — {listing_id}",
                        "description": f"Confirmation code {code}",
                        "slot": slot,
                        "code": code,
                        "listing_id": listing_id,
                        "email": email,
                    },
                )
