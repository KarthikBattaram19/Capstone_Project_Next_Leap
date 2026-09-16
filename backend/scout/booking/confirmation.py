"""Generate → email → discard. The booking stands whether or not the mail goes (spec §2.5, §6.7).

Every outcome is a status, never an exception: this runs as a task nobody awaits (the HTTP
route and the voice flow both answer before the mail goes, L8), so anything it raised would be
swallowed and the renter left reading "on its way" for ever. That is also why the outcome is
kept per code - the screen has no other way to learn it (spec §6.0 principle 4: no silent
partial state).
"""

from __future__ import annotations

import logging
import time

from scout.api.ratelimit import RateLimiter
from scout.booking.pdf import render_confirmation_pdf
from scout.platform import telemetry

log = logging.getLogger(__name__)

# What the renter is told for each status - spoken, and shown verbatim on screen. None of them
# says or implies the booking is in doubt: the code is authoritative, not the document (§6.51).
PDF_TELL: dict[str, str] = {
    "pending": "I'm emailing the confirmation PDF now.",
    "sent": "The confirmation PDF has been emailed to you.",
    "failed": (
        "The PDF couldn't be emailed, but your booking stands and your code still works. "
        "You can download the PDF, or ask for the email again."
    ),
    "render_failed": (
        "The PDF couldn't be made just now, but your booking stands and your code still works. "
        "Try downloading it or emailing it again in a moment."
    ),
    "rate_limited": (
        "That PDF has already been emailed three times in the last hour, so I won't send it "
        "again yet. You can download it instead."
    ),
    "not_applicable": "There's no email on record for this booking yet. You can download the PDF.",
}


class ConfirmationSender:
    def __init__(self, gmail, vm, limiter: RateLimiter | None = None) -> None:
        self._gmail = gmail
        self._vm = vm
        self._limiter = limiter or RateLimiter(3, 3600)  # 3 sends per code per hour (§6.52)
        self._outcome: dict[str, tuple[str, float]] = {}  # code -> (last delivery status, when)

    def render(self, booking) -> bytes:
        """The PDF for one booking, in memory. Raises if it cannot be made; the download route
        turns that into a plain answer, `send` into the `render_failed` status."""
        card = self._vm.card(booking.listing_id, 1, None)
        with telemetry.span("pdf.render"):
            return render_confirmation_pdf(booking, card)

    def status(self, code: str) -> str | None:
        """The last delivery outcome for this code, or None if there is none to report. It is
        forgotten after the limiter's window: an outcome older than that is no longer news."""
        hit = self._outcome.get(code)
        if hit is None:
            return None
        if time.monotonic() - hit[1] > self._limiter.per:
            del self._outcome[code]
            return None
        return hit[0]

    async def send(self, booking) -> str:
        if not self._limiter.allow(booking.code):
            # An answer to THIS request, not a delivery outcome: an email that already arrived
            # must not start reading as "rate limited" on the screen (§6.52).
            status = "rate_limited"
        else:
            self._record(booking.code, "pending")
            status = await self._deliver(booking)
            self._record(booking.code, status)
        # The code is not personal data; the address never reaches the log (spec §5.4).
        log.info("confirmation email %s for booking %s", status, booking.code)
        return status

    async def _deliver(self, booking) -> str:
        try:
            pdf = self.render(booking)  # bytes in memory only
        except Exception as e:  # noqa: BLE001 — §6.51: a PDF that cannot be made is a status
            log.warning("confirmation PDF render failed for %s: %s", booking.code, type(e).__name__)
            return "render_failed"
        try:
            await self._gmail.send_pdf(
                booking.email,
                f"Your site visit — code {booking.code}",
                f"Your visit is confirmed. Code: {booking.code}. See the attached PDF.",
                pdf,
                f"visit-{booking.code}.pdf",
            )
            return "sent"
        except Exception:  # noqa: BLE001 — any failure here is "failed", never a crash
            return "failed"  # the booking stands; the code is authoritative
        finally:
            del pdf  # nothing retained

    def _record(self, code: str, status: str) -> None:
        now = time.monotonic()
        self._outcome[code] = (status, now)
        # Prune on write, so a long-running process does not keep every code it ever saw.
        for stale in [c for c, (_, at) in self._outcome.items() if now - at > self._limiter.per]:
            del self._outcome[stale]
