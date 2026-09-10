"""Half-landed calendar writes are repair work behind the scenes, not a booking state (arch §10.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class Job:
    op: str  # "insert" | "delete"
    calendar_id: str
    code: str
    payload: dict
    attempts: int = 0


@dataclass
class ReconcileQueue:
    """In memory, like the availability overlay (AD-11): a restart drops unfinished repairs.

    Nothing is misreported by that — `lookup` rebuilds `calendar_complete` from what
    `find_by_code` can actually see, so a half-written booking still reports `reconciling`
    after a restart; it simply stops repairing itself until an operator re-runs it.
    """

    calendar: object
    jobs: list[Job] = field(default_factory=list)

    def enqueue(self, op: str, calendar_id: str, code: str, payload: dict) -> None:
        self.jobs.append(Job(op, calendar_id, code, payload))

    def drop(self, code: str) -> int:
        """Forget every queued repair for a code.

        Called before a cancel or a move, so a retried insert cannot re-create a visit the
        renter has just cancelled (measured 2026-09-10: a half-landed booking, cancelled,
        came back on the Owner calendar from this queue).
        """
        before = len(self.jobs)
        self.jobs = [j for j in self.jobs if j.code != code]
        return before - len(self.jobs)

    def pending_for(self, code: str) -> int:
        return sum(1 for j in self.jobs if j.code == code)

    async def run_once(self) -> None:
        for j in list(self.jobs):
            try:
                if j.op == "insert":
                    # A write can fail after the event was created (a timeout on the
                    # response, not the write). The code stamped on every event is the
                    # idempotency key: if this half already exists, do not insert twice.
                    existing = await self.calendar.find_by_code(j.code)
                    if not any(e.calendar_id == j.calendar_id for e in existing):
                        await self.calendar.insert(j.calendar_id, **j.payload)
                else:
                    # `delete` already treats "already gone" as success.
                    await self.calendar.delete(j.calendar_id, j.payload["event_id"])
                self.jobs.remove(j)
            except Exception:  # noqa: BLE001 -- any failure stays queued for the next pass
                j.attempts += 1

    async def run_forever(self, interval_s: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval_s)
            await self.run_once()
