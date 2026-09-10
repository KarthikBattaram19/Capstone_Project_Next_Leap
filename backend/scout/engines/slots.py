"""Slot arithmetic in Asia/Kolkata, explicitly, always (spec §6.47). The server is not in India."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil import parser as dateparser

from scout.domain.booking import IST, Slot

__all__ = ["IST", "OutsideInventory", "Slot", "SlotService"]


@dataclass(frozen=True)
class OutsideInventory:
    reason: str


class SlotService:
    def __init__(self, window_days: int = 7, start_hour: int = 10, end_hour: int = 18) -> None:
        self.window_days = window_days
        self.start_hour = start_hour
        self.end_hour = end_hour

    def window(self, now: datetime) -> tuple[datetime, datetime]:
        n = now.astimezone(IST)
        start = (n + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        if start.hour < self.start_hour:
            start = start.replace(hour=self.start_hour)
        elif start.hour >= self.end_hour:
            start = (start + timedelta(days=1)).replace(hour=self.start_hour)
        return start, start + timedelta(days=self.window_days)

    def free_slots(self, busy: list[tuple[datetime, datetime]], now: datetime) -> list[Slot]:
        start, end = self.window(now)
        busy_ist = [(a.astimezone(IST), b.astimezone(IST)) for a, b in busy]
        out: list[Slot] = []
        t = start
        while t < end:
            if self.start_hour <= t.hour < self.end_hour:
                s, e = t, t + timedelta(hours=1)
                if not any(a < e and b > s for a, b in busy_ist):
                    out.append(Slot(s, e))
            t += timedelta(hours=1)
        return out

    def first(self, slots: list[Slot], n: int = 3) -> list[Slot]:
        return slots[:n]

    def has_started(self, slot: Slot, now: datetime) -> bool:
        return now.astimezone(IST) >= slot.start.astimezone(IST)

    def parse_requested(self, text_or_iso: str, now: datetime) -> Slot | OutsideInventory:
        # A time with no date ("4 pm", "Tuesday at 4 pm") is completed from the IST calendar
        # date of `now`, never from dateutil's server-local clock (spec §6.47).
        base = now.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            dt = dateparser.parse(text_or_iso, default=base)
        except (ValueError, OverflowError):
            return OutsideInventory(
                "I couldn't read that time. Say a day and an hour, like 'Tuesday at 4 pm'."
            )
        dt = dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)
        dt = dt.replace(minute=0, second=0, microsecond=0)
        start, end = self.window(now)
        rule = (
            "Visits are one-hour slots between 10:00 and 18:00 IST "
            f"within the next {self.window_days} days."
        )
        if not self.start_hour <= dt.hour < self.end_hour:
            return OutsideInventory(rule + f" {dt.strftime('%H:%M')} is outside that.")
        if not start <= dt < end:
            return OutsideInventory(rule + f" {dt.strftime('%d %B')} is outside that window.")
        return Slot(dt, dt + timedelta(hours=1))
