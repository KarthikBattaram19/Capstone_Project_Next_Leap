"""The confirmation PDF: in memory, the code, the visit in IST, the labelled placeholder."""

from datetime import datetime

from scout.booking.pdf import render_confirmation_pdf
from scout.contract.viewmodels import CardVM, CommuteRowVM
from scout.domain.booking import IST, Booking, BookingState, Slot


def test_pdf_contains_code_ist_time_and_labelled_placeholder():
    row = CommuteRowVM(
        what="Metro",
        value_text="1.1 km",
        badge="by route",
        full_label="[OSM routing — precomputed 2026-09-02]",
        spoken="",
    )
    card = CardVM(
        listing_id="a",
        rank=1,
        locality="Koramangala",
        society_name="X",
        rent="₹35,000 / month",
        deposit="not stated",
        maintenance="not stated",
        bhk_type="2BHK",
        square_footage="not stated",
        floor="3",
        parking="both",
        furnishing="semi furnished",
        amenities=[],
        available_from="not stated",
        transit=row,
    )
    b = Booking(
        "AB12CD",
        "a",
        Slot(datetime(2026, 9, 2, 16, tzinfo=IST), datetime(2026, 9, 2, 17, tzinfo=IST)),
        BookingState.BOOKED,
        "t@x",
    )
    pdf = render_confirmation_pdf(b, card)
    assert pdf[:4] == b"%PDF"
    text = pdf.decode("latin-1")
    for needle in ("AB12CD", "999999999", "demo placeholder", "Koramangala", "IST"):
        assert needle in text or needle.encode("latin-1") in pdf
