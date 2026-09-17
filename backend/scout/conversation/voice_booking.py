"""Booking by voice: the same BookingService the HTTP routes use (arch §6.2)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta

from scout.api.http import NOT_FOUND_TELL
from scout.booking.service import (
    ALPHABET,
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
    AwaitCode,
    AwaitEmail,
    AwaitSlotChoice,
    ConfirmCancel,
    ConfirmEmail,
    Session,
)
from scout.domain.booking import IST, Slot

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)

_CANCEL_WORD = re.compile(r"\b(?:cancel\w*|call(?:ing|ed)?\s+(?:\w+\s+)?off)\b", re.IGNORECASE)
_BOOKING_WORD = re.compile(r"\b(?:visits?|bookings?|appointments?|codes?)\b", re.IGNORECASE)


def _asks_to_cancel(res: Job1Result, text: str) -> bool:
    """A cancel needs a cancel word about a visit, booking, appointment or code - or a code.

    Production, 2026-09-17: "Okay. I'm ending the conversation here." came back from Job 1 as
    a cancel, and she asked for the six-character confirmation code.
    """
    if len((res.code or "").upper().replace(" ", "")) == 6:
        return True
    return bool(_CANCEL_WORD.search(text) and _BOOKING_WORD.search(text))


_TOKEN = re.compile(r"[A-Za-z0-9']+")
_DIGIT_WORDS = {"two": "2", "three": "3", "four": "4", "five": "5"}
_DIGIT_WORDS |= {"six": "6", "seven": "7", "eight": "8", "nine": "9"}
# Capitals and digit-words that are not a code: "2BHK", "40K", "11 AM", "the 3rd".
_NOT_CODE = re.compile(r"^(?:\d+(?:BHK|RK|K|KM|AM|PM|ST|ND|RD|TH)|BHK|RK|PG|AM|PM|KM|SQ|FT)$")
# Numbers that are something else, taken out before the words are read: an amount, a bedroom
# count, a time, a date, a size. Batch review, 2026-09-17: after the code question "A 3 BHK
# in HSR Layout under 45,000" read as the characters "345" and was asked for the code again.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_NOT_CODE_NUMBER = re.compile(
    r"\d{1,3}(?:,\d{2,3})+|(?:₹|\brs\.?)\s*\d[\d,]*|\b\d{2,}\s*k\b|"
    r"\b\d+(?:\.\d+)?\s*(?:lakhs?|thousand|rupees|crores?|sq|square|bhk|rk)\b|"
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.|o'?clock)|"
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def spoken_code(text: str, place_words: set[str] = frozenset()) -> str:
    """The characters of a confirmation code in what was said, joined; "" when none.

    A word counts when every character is in the code alphabet and it has a digit, or is
    written in capitals ("9VR7JP", "9 V R 7 J P"), or is a digit said as a word ("nine").
    Capitals that name a place ("HSR", "BTM") and "2BHK"-like words do not. Production,
    2026-09-17: "9VR7JP." after the code question was read by Job 1 cold and answered "I can
    only help in English"; "I was saying 9BRJ or 7JP." became "9BRJ isn't covered".
    """
    chars: list[str] = []
    for tok in _TOKEN.findall(_NOT_CODE_NUMBER.sub(" ", text)):
        if "'" in tok:
            continue
        if tok.lower() in _DIGIT_WORDS:
            chars.append(_DIGIT_WORDS[tok.lower()])
            continue
        up = tok.upper()
        if len(up) > 6 or any(c not in ALPHABET for c in up) or _NOT_CODE.match(up):
            continue
        has_digit = any(c.isdigit() for c in up)
        if has_digit or (tok.isupper() and up not in place_words):
            chars.append(up)
    return "".join(chars)


_WORD_NUMBERS = {
    w: i + 1
    for i, w in enumerate(
        ["one", "two", "three", "four", "five", "six"]
        + ["seven", "eight", "nine", "ten", "eleven", "twelve"]
    )
}
_N = r"\b(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")"
_MERIDIEM = re.compile(_N + r"(?::\d{2})?\s*([ap])\.?\s*m\b\.?", re.IGNORECASE)
_CLOCK = re.compile(r"\b(\d{1,2}):\d{2}\b")
_BARE = re.compile(  # "at 11", "11 o'clock" — never "at 5 km" or "at 40k"
    r"\bat\s+" + _N[2:] + r"\b(?!\s*(?:st|nd|rd|th|k|km|lakh|minutes?|mins?)\b)"
    r"|" + _N + r"\s*o'?\s*clock\b",
    re.IGNORECASE,
)
_MONTHS = "january february march april may june july august september october november december"
_MONTH = "(" + "|".join(_MONTHS.split()) + ")"
_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r"\b"
    r"|\b" + _MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_WEEKDAY = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
)
_RELATIVE = re.compile(r"\b(today|tomorrow)\b", re.IGNORECASE)


def _number(tok: str) -> int:
    return int(tok) if tok.isdigit() else _WORD_NUMBERS[tok.lower()]


def match_offered(text: str, slots: list[Slot], now: datetime) -> Slot | None | bool:
    """Which offered slot a spoken time names, in code, before anything Job 1 made of it.

    Job 1 is not told a slot choice is pending, and on production (2026-09-17) it called
    "Thursday 17 September at 10 am" — the renter reading an offered slot back, and the very
    words the slot chips send — a reschedule with no code. Returns the one slot named; False
    when a day or hour was said that names no single offered slot; None when no time was said.
    """
    hours: set[int] = set()
    for m in _MERIDIEM.finditer(text):
        hours.add(_number(m.group(1)) % 12 + (12 if m.group(2).lower() == "p" else 0))
    for m in _CLOCK.finditer(text):
        hours.add(int(m.group(1)))
    for m in _BARE.finditer(text):
        hours.add(_number(m.group(1) or m.group(2)))
    # Visits run 10:00-18:00, so a bare "at 2" or "2:00" can only mean 2 pm.
    hours = {h + 12 if 1 <= h < 8 else h for h in hours}

    weekdays = {m.group(1).lower() for m in _WEEKDAY.finditer(text)}
    dates = {
        (int(m.group(1) or m.group(4)), (m.group(2) or m.group(3)).lower())
        for m in _DATE.finditer(text)
    }
    today = now.astimezone(IST).date()
    relative = {
        today + timedelta(days=1 if m.group(1).lower() == "tomorrow" else 0)
        for m in _RELATIVE.finditer(text)
    }

    if not (hours or weekdays or dates or relative):
        return None
    if len(hours) > 1:
        return False

    def said(slot: Slot) -> bool:
        s = slot.start.astimezone(IST)
        return (
            (not hours or s.hour in hours)
            and weekdays <= {s.strftime("%A").lower()}
            and dates <= {(s.day, s.strftime("%B").lower())}
            and relative <= {s.date()}
        )

    named = [s for s in slots if said(s)]
    return named[0] if len(named) == 1 else False


def _which_of_those(slots: list[Slot]) -> NeedsInput:
    return NeedsInput(
        question="Which of those slots?",
        field="slot",
        options=[s.spoken() for s in slots],
        spoken="I can offer " + ", ".join(s.spoken() for s in slots) + ". Which one suits you?",
    )


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

    def names_offered_slot(self, session: Session, text: str) -> bool:
        """Whether a pending slot question is answered by a day or time in the words, read
        before Job 1 so that Job 1's reading of "11 am" (unclear, a goodbye) cannot take the
        turn. `handle` then matches the time itself. "The second one" still goes to Job 1."""
        p = session.pending
        return isinstance(p, AwaitSlotChoice) and (
            match_offered(text, p.slots, self.booking.now()) is not None
        )

    async def handle(self, session: Session, res: Job1Result, text: str) -> TurnOutcome | None:
        p = session.pending
        if p is None and res.intent not in BOOKING_INTENTS:
            return None  # nothing pending and not a booking sentence: not ours

        chosen = None
        if isinstance(p, AwaitSlotChoice):
            # A spoken time outranks Job 1's reading: "the one at 11" is not "the first one".
            chosen = match_offered(text, p.slots, self.booking.now())
            if chosen is False:
                return _which_of_those(p.slots)
            if chosen is None and (res.slot_choice or res.reference):
                n = res.slot_choice or res.reference
                if not 1 <= n <= len(p.slots):
                    return _which_of_those(p.slots)
                chosen = p.slots[n - 1]

        # Reschedule completion: the code is already known and the address is already on
        # the event, so the choice goes straight to the calendar — no email step.
        if chosen is not None and session.reschedule_code:
            return await self._reschedule_to(session, session.reschedule_code, chosen)

        if chosen is not None:
            session.pending = AwaitEmail(p.listing_id, chosen)
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
            if not _asks_to_cancel(res, text):
                return None
            session.reschedule_code = None
            code = (res.code or "").upper().replace(" ", "")
            if len(code) != 6:
                session.pending = AwaitCode("cancel")
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
                session.pending = AwaitCode("reschedule")
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
