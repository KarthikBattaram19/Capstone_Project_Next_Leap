"""ConfirmationSender: every outcome is a status, never an exception (spec §6.7, §6.51, §6.52).

The sender runs as a task nobody awaits, so an exception would vanish and leave the renter
reading "on its way" for ever. These pin that each failure comes back as its own status, and
that the outcome is kept where the screen can ask for it.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from scout.api.ratelimit import RateLimiter
from scout.booking import confirmation
from scout.booking.confirmation import PDF_TELL, ConfirmationSender
from scout.contract.viewmodels import PdfStatus
from scout.domain.booking import Booking, BookingState, Slot

START = datetime(2026, 9, 2, 5, 30, tzinfo=UTC)


def booking(code: str = "ABC234") -> Booking:
    return Booking(
        code=code,
        listing_id="kor-001",
        slot=Slot(START, START + timedelta(hours=1)),
        state=BookingState.BOOKED,
        email="renter@example.com",
    )


class FakeVM:
    def card(self, listing_id, rank, commute):
        return object()


class FakeGmail:
    def __init__(self, fail: bool = False, gate: asyncio.Event | None = None):
        self.fail, self.gate, self.sent = fail, gate, []

    async def send_pdf(self, to, subject, body, pdf, filename):
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("gmail down")
        self.sent.append((to, filename, pdf))
        return "msg-1"


@pytest.fixture(autouse=True)
def fake_render(monkeypatch):
    monkeypatch.setattr(confirmation, "render_confirmation_pdf", lambda b, card: b"%PDF-fake")


async def test_a_delivered_email_is_sent_and_remembered():
    gmail = FakeGmail()
    s = ConfirmationSender(gmail, FakeVM())

    assert await s.send(booking()) == "sent"
    assert s.status("ABC234") == "sent"
    assert gmail.sent == [("renter@example.com", "visit-ABC234.pdf", b"%PDF-fake")]


async def test_a_failed_email_is_failed_not_an_exception():
    s = ConfirmationSender(FakeGmail(fail=True), FakeVM())
    assert await s.send(booking()) == "failed"
    assert s.status("ABC234") == "failed"


async def test_a_pdf_that_cannot_be_made_is_render_failed_and_nothing_is_mailed(monkeypatch):
    """Spec §6.51. The render used to sit outside the try, so this raised out of a task nobody
    awaited: the status was never set and the screen said "on its way" for ever."""

    def broken(b, card):
        raise ValueError("reportlab exploded")

    monkeypatch.setattr(confirmation, "render_confirmation_pdf", broken)
    gmail = FakeGmail()
    s = ConfirmationSender(gmail, FakeVM())

    assert await s.send(booking()) == "render_failed"
    assert s.status("ABC234") == "render_failed"
    assert gmail.sent == []


async def test_a_listing_the_view_cannot_find_is_also_render_failed():
    class MissingListing:
        def card(self, *a):
            raise KeyError("kor-001")

    s = ConfirmationSender(FakeGmail(), MissingListing())
    assert await s.send(booking()) == "render_failed"


async def test_the_fourth_send_in_an_hour_is_rate_limited_and_the_delivery_record_stands():
    """Spec §6.52, and the limiter the walkthrough found untested. "Rate limited" answers the
    request that was refused; it must not overwrite the fact that an email arrived."""
    gmail = FakeGmail()
    s = ConfirmationSender(gmail, FakeVM(), RateLimiter(3, 3600))

    assert [await s.send(booking()) for _ in range(3)] == ["sent", "sent", "sent"]
    assert await s.send(booking()) == "rate_limited"
    assert len(gmail.sent) == 3
    assert s.status("ABC234") == "sent"


async def test_the_limit_is_per_booking():
    s = ConfirmationSender(FakeGmail(), FakeVM(), RateLimiter(1, 3600))
    assert await s.send(booking("ABC234")) == "sent"
    assert await s.send(booking("XYZ789")) == "sent"


async def test_the_status_reads_pending_while_the_email_is_going():
    gate = asyncio.Event()
    s = ConfirmationSender(FakeGmail(gate=gate), FakeVM())

    task = asyncio.create_task(s.send(booking()))
    await asyncio.sleep(0)
    assert s.status("ABC234") == "pending"
    gate.set()
    assert await task == "sent"


async def test_an_outcome_older_than_the_limit_window_is_forgotten():
    s = ConfirmationSender(FakeGmail(), FakeVM(), RateLimiter(3, 0.05))
    await s.send(booking())
    await asyncio.sleep(0.1)
    assert s.status("ABC234") is None
    assert s.status("NEVER1") is None


def test_every_status_the_sender_can_produce_is_in_the_contract_and_has_a_sentence():
    """render_failed and rate_limited were produced but missing from PdfStatus, so a view built
    from either would have failed validation."""
    produced = {"pending", "sent", "failed", "render_failed", "rate_limited", "not_applicable"}
    assert produced == set(PdfStatus.__args__)
    assert produced == set(PDF_TELL)
    booking_stands = ("failed", "render_failed")
    assert all("booking stands" in PDF_TELL[s] for s in booking_stands)
