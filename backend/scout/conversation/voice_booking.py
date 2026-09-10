"""Booking by voice: the same BookingService the HTTP routes use (arch §6.2)."""

from __future__ import annotations

import asyncio
import re

from scout.api.http import NOT_FOUND_TELL
from scout.booking.service import (
    AlreadyStarted,
    Booked,
    Cancelled,
    NoSlots,
    NotFound,
    Rescheduled,
    SlotTaken,
    Unchanged,
    Withdrawn,
)
from scout.contract.outcome import Answered, NeedsInput, TurnOutcome
from scout.conversation.booking_flow import BOOKING_INTENTS
from scout.conversation.job1 import Job1Result
from scout.conversation.session import (
    AwaitEmail,
    AwaitSlotChoice,
    ConfirmCancel,
    ConfirmEmail,
    Session,
)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)


def spell(email: str) -> str:
    """Every character hyphen-separated; "@" as " at ", each "." in the domain as " dot "."""
    local, _, domain = email.partition("@")
    return "-".join(local) + " at " + " dot ".join("-".join(p) for p in domain.split("."))


class VoiceBookingFlow:
    def __init__(self, booking, vm, sender, orchestrator_view) -> None:
        self.booking = booking
        self.vm = vm
        self.sender = sender
        self._view = orchestrator_view

    async def handle(self, session: Session, res: Job1Result, text: str) -> TurnOutcome | None:
        p = session.pending
        if p is None and res.intent not in BOOKING_INTENTS:
            return None  # nothing pending and not a booking sentence: not ours

        # Reschedule completion: the code is already known and the address is already on
        # the event, so the choice goes straight to the calendar — no email step.
        if (
            isinstance(p, AwaitSlotChoice)
            and session.reschedule_code
            and (res.slot_choice or res.reference)
        ):
            n = res.slot_choice or res.reference
            if not 1 <= n <= len(p.slots):
                return NeedsInput(
                    question="Which of those slots?",
                    field="slot",
                    spoken="Which of those slots — first, second or third?",
                )
            return await self._reschedule_to(session, session.reschedule_code, p.slots[n - 1])

        if isinstance(p, AwaitSlotChoice) and (res.slot_choice or res.reference):
            n = res.slot_choice or res.reference
            if not 1 <= n <= len(p.slots):
                return NeedsInput(
                    question="Which of those slots?",
                    field="slot",
                    spoken="Which of those slots — first, second or third?",
                )
            session.pending = AwaitEmail(p.listing_id, p.slots[n - 1])
            return NeedsInput(
                question="What email should I send the confirmation to?",
                field="email",
                spoken="What email address should I send the confirmation to?",
            )

        if isinstance(p, AwaitEmail) and (res.intent == "provide_email" or res.email):
            email = (res.email or "").strip().lower()
            if not _EMAIL.match(email):
                return NeedsInput(
                    question="I didn't get a valid email — please say it again.",
                    field="email",
                    spoken="I didn't get a valid email address. Please say it again, slowly.",
                )
            session.pending = ConfirmEmail(p.listing_id, p.slot, email)
            return NeedsInput(  # §6.50 — read back character by character before sending
                question=f"Is that {email}?",
                field="email_confirm",
                options=["yes", "no"],
                spoken=f"Let me read that back: {spell(email)}. Is that right?",
            )

        if isinstance(p, ConfirmEmail) and res.intent in ("confirm_yes", "confirm_no"):
            if res.intent == "confirm_no":
                session.pending = AwaitEmail(p.listing_id, p.slot)
                return NeedsInput(
                    question="Please say the email again.",
                    field="email",
                    spoken="Please say the email again.",
                )
            session.pending = None
            session.email = p.email
            r = await self.booking.confirm(p.listing_id, p.slot, p.email)
            if isinstance(r, Withdrawn):  # §6.43 — remove it and re-read what is left
                session.shortlist = _without(session.shortlist, p.listing_id)
                session.last_read_order = session.shortlist.order
                vm = self._view(
                    session,
                    notices=[
                        "One listing in your shortlist is no longer available and has been removed."
                    ],
                )
                return Answered(
                    view_model=vm,
                    spoken="That flat has just come off the market, so I haven't booked it. "
                    "It's been removed from your shortlist. " + _reread(vm),
                )
            if isinstance(r, SlotTaken):  # §6.41 — re-offer, the flow stays open
                session.pending = AwaitSlotChoice(p.listing_id, r.alternatives)
                return NeedsInput(
                    question="That hour was just taken.",
                    field="slot",
                    options=[s.spoken() for s in r.alternatives],
                    spoken="That hour was just taken. I can offer "
                    + ", ".join(s.spoken() for s in r.alternatives)
                    + ". Which one?",
                )
            assert isinstance(r, Booked)
            asyncio.create_task(self._send(r.booking))  # L8, off the interactive path
            vm = self._view(session)
            vm.booking = self.vm.booking(r.booking)
            return Answered(view_model=vm, spoken=r.tell + " I'm emailing the PDF now.")

        if isinstance(p, ConfirmCancel) and res.intent in ("confirm_yes", "confirm_no"):
            session.pending = None
            if res.intent == "confirm_no":
                return Answered(view_model=self._view(session), spoken="Okay, your visit stands.")
            r = await self.booking.cancel(p.code)
            spoken = {
                NotFound: NOT_FOUND_TELL,
                AlreadyStarted: "That visit has already started, so it can't be cancelled.",
            }.get(type(r), "Cancelled. Both calendar entries are being removed.")
            vm = self._view(session)
            if isinstance(r, Cancelled):
                vm.booking = None
            return Answered(view_model=vm, spoken=spoken)

        if res.intent == "book":
            session.reschedule_code = None  # an abandoned reschedule must not hijack this one
            lid = session.focus_listing_id or (
                session.last_read_order[res.reference - 1]
                if res.reference and session.last_read_order
                else None
            )
            if lid is None:
                return NeedsInput(
                    question="Which listing would you like to visit?",
                    field="reference",
                    spoken="Which listing would you like to visit?",
                )
            r = await self.booking.offer(lid)
            if isinstance(r, NoSlots):
                return Answered(
                    view_model=self._view(session),
                    spoken="There are no free visit slots in the next seven days for that "
                    "owner. Try another listing, or ask again later.",
                )
            session.pending = AwaitSlotChoice(lid, r)
            return NeedsInput(
                question="Pick a slot",
                field="slot",
                options=[s.spoken() for s in r],
                spoken="I can offer " + ", ".join(s.spoken() for s in r) + ". Which suits you?",
            )

        if res.intent == "cancel":
            session.reschedule_code = None
            code = (res.code or "").upper().replace(" ", "")
            if len(code) != 6:
                return NeedsInput(
                    question="What's the six-character confirmation code?",
                    field="code",
                    spoken="What's the six-character confirmation code?",
                )
            b = await self.booking.lookup(code)
            if b is None:
                return Answered(view_model=self._view(session), spoken=NOT_FOUND_TELL)
            card = self.vm.card(b.listing_id, 1, None)
            session.pending = ConfirmCancel(code)
            return NeedsInput(
                question=f"Cancel the visit to {card.locality} on {b.slot.spoken()}?",
                field="cancel_confirm",
                options=["yes", "no"],
                spoken=f"That's the {card.bhk_type} in {card.locality} on {b.slot.spoken()}. "
                "Cancel it?",
            )

        if res.intent == "reschedule":
            code = (res.code or "").upper().replace(" ", "")
            if len(code) != 6:
                return NeedsInput(
                    question="What's the confirmation code?",
                    field="code",
                    spoken="What's the six-character confirmation code?",
                )
            b = await self.booking.lookup(code)
            if b is None:
                return Answered(view_model=self._view(session), spoken=NOT_FOUND_TELL)
            r = await self.booking.offer(b.listing_id)
            if isinstance(r, NoSlots):
                return Answered(
                    view_model=self._view(session),
                    spoken="No free slots in the next seven days; your current visit stands.",
                )
            session.pending = AwaitSlotChoice(b.listing_id, r)
            session.reschedule_code = code
            return NeedsInput(
                question="Pick a new slot",
                field="slot",
                options=[s.spoken() for s in r],
                spoken="I can move it to " + ", ".join(s.spoken() for s in r) + ". Which one?",
            )

        return None

    async def _reschedule_to(self, session: Session, code: str, slot) -> TurnOutcome:
        r = await self.booking.reschedule(code, slot)
        if isinstance(r, SlotTaken):  # re-offer; the code and the pending choice stay
            session.pending = AwaitSlotChoice(session.pending.listing_id, r.alternatives)
            return NeedsInput(
                question="That hour was just taken.",
                field="slot",
                options=[s.spoken() for s in r.alternatives],
                spoken="That hour was just taken. I can move it to "
                + ", ".join(s.spoken() for s in r.alternatives)
                + ". Which one?",
            )
        session.pending = None
        session.reschedule_code = None
        vm = self._view(session)
        if isinstance(r, Rescheduled):
            asyncio.create_task(self._send(r.booking))  # the replacement PDF, off the path
            vm.booking = self.vm.booking(r.booking)
            return Answered(view_model=vm, spoken=r.tell + " I'm emailing the updated PDF now.")
        if isinstance(r, Unchanged):  # §6.49 — nothing deleted, nothing recreated
            vm.booking = self.vm.booking(r.booking)
            return Answered(
                view_model=vm,
                spoken="That's the slot you already have, so nothing has changed. "
                f"Your code is still {' '.join(code)}.",
            )
        spoken = {
            NotFound: NOT_FOUND_TELL,
            AlreadyStarted: "That visit has already started, so it can't be moved.",
        }[type(r)]
        return Answered(view_model=vm, spoken=spoken)

    async def _send(self, booking) -> None:
        booking.pdf_status = await self.sender.send(booking)


def _without(shortlist, listing_id):
    from scout.domain.shortlist import Shortlist, ShortlistEntry

    kept = [e for e in shortlist.matched if e.listing_id != listing_id]
    return Shortlist(
        matched=tuple(ShortlistEntry(e.listing_id, i + 1) for i, e in enumerate(kept)),
        unknown=shortlist.unknown,
        excluded=shortlist.excluded,
    )


def _reread(vm) -> str:
    if not vm.shortlist or not vm.shortlist.order:
        return "Nothing else is left in the shortlist."
    cards = [c for g in vm.shortlist.groups for c in g.cards]
    return (
        "What remains: "
        + "; ".join(f"{c.bhk_type} in {c.locality} at {c.rent}" for c in cards[:3])
        + "."
    )
