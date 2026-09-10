"""Booking routes over the fake calendar (Task 3.3): no Google client is ever built."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from scout.api.http import NOT_FOUND_TELL
from scout.booking.reconcile import ReconcileQueue
from scout.booking.service import BookingService
from scout.config import Settings
from scout.contract.viewmodels import BookingVM
from scout.main import create_app
from tests.unit.booking.test_service import FakeCal

NOW = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)  # 09:00 IST Tuesday
LISTING = "kor-001"  # from tests/fixtures/bundle_min/listings.json


def make_app(bundle_dir: str):
    app = create_app(
        Settings(
            _env_file=None,
            cors_allowed_origins="http://localhost:3000",
            bundle_dir=bundle_dir,
            operator_token="tok",
        )
    )
    cal = FakeCal()
    app.state.booking = BookingService(
        cal, app.state.slots, app.state.availability, ReconcileQueue(cal), now=lambda: NOW
    )
    return app, cal


def _book(c: TestClient):
    slots = c.post("/bookings/slots", json={"listing_id": LISTING}).json()["slots"]
    assert len(slots) == 3
    return c.post(
        "/bookings",
        json={
            "session_id": "s1",
            "listing_id": LISTING,
            "slot_start_ist": slots[0]["start_ist"],
            "email": "t@x",
        },
    )


def test_happy_path_returns_a_booking_vm_with_a_six_char_code(bundle_min):
    app, cal = make_app(bundle_min)
    with TestClient(app) as c:  # runs the lifespan: the reconcile loop starts and stops
        r = _book(c)
    assert r.status_code == 200, r.text
    body = r.json()
    vm = BookingVM.model_validate(body["booking"])
    assert len(vm.code) == 6 and vm.state == "booked" and vm.calendar_sync == "complete"
    assert vm.listing_id == LISTING
    assert " ".join(vm.code) in body["spoken"]
    assert {c for c, *_ in cal.events.values()} == {"T", "O"}


def test_unknown_and_cancelled_codes_get_exactly_the_same_404(bundle_min):
    app, _ = make_app(bundle_min)
    c = TestClient(app)
    code = _book(c).json()["booking"]["code"]
    first = c.post(f"/bookings/{code}/cancel")
    assert first.status_code == 200 and first.json()["state"] == "cancelled"
    cancelled = c.post(f"/bookings/{code}/cancel")
    unknown = c.post("/bookings/ZZZZZZ/cancel")
    assert cancelled.status_code == 404 and unknown.status_code == 404
    assert cancelled.json() == unknown.json() == {"detail": NOT_FOUND_TELL}


def test_eleventh_cancel_within_a_minute_from_one_client_is_429(bundle_min):
    app, _ = make_app(bundle_min)
    c = TestClient(app)
    for _ in range(10):
        assert c.post("/bookings/ZZZZZZ/cancel").status_code == 404
    assert c.post("/bookings/ZZZZZZ/cancel").status_code == 429


def test_admin_availability_needs_the_token_and_flips_the_shared_flag(bundle_min):
    app, _ = make_app(bundle_min)
    c = TestClient(app)
    body = {"listing_id": LISTING, "available": False}
    assert c.post("/admin/availability", json=body).status_code == 401
    r = c.post("/admin/availability", json=body, headers={"x-operator-token": "tok"})
    assert r.status_code == 200 and r.json() == body
    assert app.state.availability.is_available(LISTING) is False
    # One register, shared: the orchestrator and the booking service see the same flip.
    assert app.state.orchestrator.availability is app.state.availability
    assert _book(c).status_code == 409


def test_a_calendar_failure_is_a_503_naming_the_capability_not_a_500(bundle_min):
    from scout.providers.google_calendar import CalendarAuthError, CalendarError

    class DownCal(FakeCal):
        async def freebusy(self, cal, start, end):
            raise CalendarError("boom")

    class AuthCal(FakeCal):
        async def freebusy(self, cal, start, end):
            raise CalendarAuthError("401", 401)

    for cal, word in ((DownCal(), "unreachable"), (AuthCal(), "operator")):
        app, _ = make_app(bundle_min)
        app.state.booking = BookingService(
            cal, app.state.slots, app.state.availability, ReconcileQueue(cal), now=lambda: NOW
        )
        r = TestClient(app).post("/bookings/slots", json={"listing_id": LISTING})
        assert r.status_code == 503, r.text
        assert word in r.json()["detail"] and r.json()["capability"] == "calendar"
