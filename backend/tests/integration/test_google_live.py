"""Google Calendar adapter against the real API. Skipped unless the Google settings are present.

Run with a populated backend/.env:  python -m pytest backend/tests/integration -q
CI never runs these — its pytest target is backend/tests/unit.

One private, attendee-free event goes onto the Owner calendar with a throwaway code, is
found by that code, and is deleted again. Nothing is left behind and no invitation is sent.
"""

import secrets
from datetime import datetime, timedelta

import pytest

from scout.config import ENV_FILE, Settings
from scout.domain.booking import IST, Slot

# Ask the same source the code under test asks. os.getenv() sees only the process
# environment, so with keys in backend/.env — where the conventions put them — these
# would skip forever while looking like they had run.
_S = Settings()
_MISSING = [
    name
    for name, value in (
        ("GOOGLE_OAUTH_CREDENTIALS", _S.google_oauth_credentials),
        ("GOOGLE_TENANT_CALENDAR_ID", _S.google_tenant_calendar_id),
        ("GOOGLE_OWNER_CALENDAR_ID", _S.google_owner_calendar_id),
    )
    if not value
]
pytestmark = pytest.mark.skipif(
    bool(_MISSING),
    reason=f"Google config not set: {', '.join(_MISSING)} (looked in the environment and {ENV_FILE})",
)


async def test_insert_find_by_code_and_delete_on_the_owner_calendar():
    from scout.providers.google_calendar import GoogleCalendarAdapter

    settings = Settings()
    ad = GoogleCalendarAdapter(settings)
    owner = settings.google_owner_calendar_id
    # A throwaway code that cannot collide with a real booking's 6-character one.
    code = "LIVE" + secrets.token_hex(4).upper()
    # Dated in the past, so nothing this test writes can ever be offered as a slot.
    start = datetime(2020, 1, 1, 10, tzinfo=IST)
    slot = Slot(start, start + timedelta(hours=1))

    event_id = await ad.insert(
        owner,
        "Adapter live check",
        "inserted by test_google_live.py; safe to delete",
        slot,
        code=code,
        listing_id="live-check",
        email="nobody@example.invalid",
    )
    try:
        refs = await ad.find_by_code(code)
        assert [r.event_id for r in refs] == [event_id]
        assert refs[0].calendar_id == owner
        assert refs[0].listing_id == "live-check"
        assert refs[0].start.astimezone(IST) == start
    finally:
        await ad.delete(owner, event_id)

    assert await ad.find_by_code(code) == []
    # Deleting again is success, not an error (already gone).
    await ad.delete(owner, event_id)
