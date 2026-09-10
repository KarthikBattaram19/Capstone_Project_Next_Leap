"""On-demand PDF; generated in memory and discarded after sending (spec §2.5)."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from scout.contract.viewmodels import CardVM
from scout.domain.booking import IST, Booking

OWNER_CONTACT = "999999999"


def render_confirmation_pdf(b: Booking, card: CardVM) -> bytes:
    buf = BytesIO()
    # reportlab 5.0.1 compresses page streams by default (rl_config.pageCompression == 1),
    # which would hide the code and the placeholder label from a byte-level check of the
    # file. Uncompressed: the content is a single short page and stays inspectable.
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=0)
    y = 800

    def line(text: str, dy: int = 18, size: int = 11) -> None:
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(50, y, text)
        y -= dy

    line("Site visit confirmation — Voice Property Scout (Bengaluru)", dy=28, size=15)
    line(f"Confirmation code: {b.code}", dy=22, size=13)
    s = b.slot.start.astimezone(IST)
    line(
        f"Visit: {s.strftime('%A %d %B %Y, %H:%M')}–"
        f"{b.slot.end.astimezone(IST).strftime('%H:%M')} IST"
    )
    line(f"Locality: {card.locality}    Society: {card.society_name}")
    line(
        f"{card.bhk_type} · Rent {card.rent} · Deposit {card.deposit} · Maintenance {card.maintenance}"
    )
    line(
        f"Size: {card.square_footage} · Floor: {card.floor} · Parking: {card.parking} · "
        f"Furnishing: {card.furnishing}"
    )
    line(
        f"Nearest transit: {card.transit.what} {card.transit.value_text} "
        f"{card.transit.badge} {card.transit.full_label}"
    )
    if card.your_commute:
        line(
            f"Your commute: {card.your_commute.value_text} {card.your_commute.badge} "
            f"{card.your_commute.full_label}"
        )
    line(
        f"Owner contact: {OWNER_CONTACT}  (demo placeholder — not a real number; "
        "intentionally 9 digits)",
        dy=22,
    )
    line(
        "Cancel or reschedule any time before the visit starts by quoting the code above.",
        dy=18,
        size=9,
    )
    c.showPage()
    c.save()
    return buf.getvalue()
