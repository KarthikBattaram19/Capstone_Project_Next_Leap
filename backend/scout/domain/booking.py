"""Booking domain types: a visit slot, its state, and the booking record (spec §2.4, §6.E)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    def spoken(self) -> str:
        s = self.start.astimezone(IST)
        hour = s.strftime("%I").lstrip("0") + s.strftime(" %p").lower()
        return f"{s.strftime('%A')} {s.day} {s.strftime('%B')} at {hour}"

    def key(self) -> str:
        return self.start.astimezone(IST).isoformat()


class BookingState(str, Enum):
    OFFERED = "offered"
    CONFIRMING = "confirming"
    BOOKED = "booked"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"


@dataclass
class Booking:
    code: str
    listing_id: str
    slot: Slot
    state: BookingState
    email: str
    tenant_event_id: str | None = None
    owner_event_id: str | None = None
    pdf_status: str = "pending"
    calendar_complete: bool = False
