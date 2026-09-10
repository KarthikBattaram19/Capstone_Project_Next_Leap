"""Generate → email → discard. The booking stands whether or not the mail goes (spec §2.5, §6.52)."""

from __future__ import annotations

import logging

from scout.api.ratelimit import RateLimiter
from scout.booking.pdf import render_confirmation_pdf
from scout.platform import telemetry

log = logging.getLogger(__name__)


class ConfirmationSender:
    def __init__(self, gmail, vm, limiter: RateLimiter | None = None) -> None:
        self._gmail = gmail
        self._vm = vm
        self._limiter = limiter or RateLimiter(3, 3600)  # 3 sends per code per hour (§6.52)

    async def send(self, booking) -> str:
        status = await self._send(booking)
        # The code is not personal data; the address never reaches the log (spec §5.4).
        log.info("confirmation email %s for booking %s", status, booking.code)
        return status

    async def _send(self, booking) -> str:
        if not self._limiter.allow(booking.code):
            return "rate_limited"
        card = self._vm.card(booking.listing_id, 1, None)
        with telemetry.span("pdf.render"):
            pdf = render_confirmation_pdf(booking, card)  # bytes in memory only
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
