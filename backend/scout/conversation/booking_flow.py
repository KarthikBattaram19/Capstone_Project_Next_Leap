"""Booking intents route here. Task 3.4 provides the real flow; until then it is a typed Failed."""

from __future__ import annotations

from typing import Protocol

from scout.contract.outcome import Failed, TurnOutcome
from scout.conversation.job1 import Job1Result
from scout.conversation.session import Session

BOOKING_INTENTS = {"book", "cancel", "reschedule", "provide_email"}

_NOT_WIRED = "Booking isn't available in this build yet."


class BookingFlow(Protocol):
    async def handle(self, session: Session, res: Job1Result, text: str) -> TurnOutcome | None: ...


class BookingNotWired:
    async def handle(self, session: Session, res: Job1Result, text: str) -> TurnOutcome | None:
        if (
            res.intent in BOOKING_INTENTS
            or res.slot_choice is not None
            or session.pending.__class__.__name__.startswith(
                ("Await", "ConfirmEmail", "ConfirmCancel")
            )
        ):
            return Failed(
                capability="calendar",
                tell_renter=_NOT_WIRED,
                retry_worth_it=False,
                spoken=_NOT_WIRED,
            )
        return None
