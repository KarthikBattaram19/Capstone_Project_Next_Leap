"""Google Calendar adapter against a faked googleapiclient service (Task 3.2).

The real `build()` never runs here: `with_service` hands the adapter a fake whose
`events()` and `freebusy()` return canned responses and record what they were asked.
"""

from datetime import datetime

import httplib2
import pytest
from googleapiclient.errors import HttpError

from scout.domain.booking import IST, Slot
from scout.providers.google_calendar import CalendarError, GoogleCalendarAdapter


class FakeExec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


class FakeEvents:
    def __init__(self):
        self.inserted, self.deleted = [], []

    def insert(self, calendarId, body):
        self.inserted.append((calendarId, body))
        return FakeExec({"id": "evt1"})

    def delete(self, calendarId, eventId):
        self.deleted.append((calendarId, eventId))
        return FakeExec(None)

    def list(self, **kw):
        # Echo back the code the adapter asked for, so the test can see the query it built.
        code = kw["privateExtendedProperty"].split("=")[1]
        return FakeExec(
            {
                "items": [
                    {
                        "id": "evt1",
                        "start": {"dateTime": "2026-09-01T16:00:00+05:30"},
                        "end": {"dateTime": "2026-09-01T17:00:00+05:30"},
                        "extendedProperties": {
                            "private": {
                                "confirmation_code": code,
                                "listing_id": "a",
                                "email": "t@x",
                            }
                        },
                    }
                ]
            }
        )


class FakeService:
    def __init__(self):
        self._events = FakeEvents()

    def events(self):
        return self._events

    def freebusy(self):
        # One busy hour, 11:00-12:00 IST on 1 September 2026, keyed by whichever
        # calendar id the request named.
        return type(
            "FB",
            (),
            {
                "query": lambda self, body: FakeExec(
                    {
                        "calendars": {
                            body["items"][0]["id"]: {
                                "busy": [
                                    {
                                        "start": "2026-09-01T11:00:00+05:30",
                                        "end": "2026-09-01T12:00:00+05:30",
                                    }
                                ]
                            }
                        }
                    }
                )
            },
        )()


async def test_insert_stamps_the_code_and_ist_times():
    svc = FakeService()
    ad = GoogleCalendarAdapter.with_service(svc, tenant_id="T", owner_id="O")
    slot = Slot(datetime(2026, 9, 1, 16, tzinfo=IST), datetime(2026, 9, 1, 17, tzinfo=IST))
    eid = await ad.insert("T", "Visit", "desc", slot, code="AB12CD", listing_id="a", email="t@x")
    assert eid == "evt1"
    cal, body = svc._events.inserted[0]
    assert cal == "T"
    assert body["start"] == {"dateTime": "2026-09-01T16:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert body["extendedProperties"]["private"]["confirmation_code"] == "AB12CD"


async def test_freebusy_parses_to_aware_datetimes():
    ad = GoogleCalendarAdapter.with_service(FakeService(), tenant_id="T", owner_id="O")
    busy = await ad.freebusy(
        "O", datetime(2026, 9, 1, tzinfo=IST), datetime(2026, 9, 8, tzinfo=IST)
    )
    assert busy[0][0].tzinfo is not None and busy[0][0].hour == 11


async def test_find_by_code_reads_both_calendars():
    refs = await GoogleCalendarAdapter.with_service(
        FakeService(), tenant_id="T", owner_id="O"
    ).find_by_code("AB12CD")
    assert {r.calendar_id for r in refs} == {"T", "O"}
    assert refs[0].listing_id == "a"


class RaisingDelete:
    """events() whose delete() fails with a given HTTP status; the URI contains 404 and 410."""

    def __init__(self, status):
        self.status = status

    def delete(self, calendarId, eventId):
        status = self.status

        class Boom:
            def execute(self):
                raise HttpError(
                    httplib2.Response({"status": status}),
                    b"",
                    uri="https://www.googleapis.com/calendar/v3/calendars/O404/events/x410",
                )

        return Boom()


async def test_delete_decides_already_gone_on_the_status_never_on_the_text():
    svc = FakeService()
    ad = GoogleCalendarAdapter.with_service(svc, tenant_id="T", owner_id="O")
    svc._events = RaisingDelete(404)
    await ad.delete("O", "x410")  # already gone is success
    svc._events = RaisingDelete(500)
    with pytest.raises(CalendarError) as ei:  # the URI says "404" and "410"; the status does not
        await ad.delete("O", "x410")
    assert ei.value.status == 500


async def test_each_worker_thread_gets_its_own_transport():
    # httplib2.Http is not thread-safe; the two parallel calendar writes must never share
    # one. Same thread -> same transport (keep-alive); a fake service -> no transport.
    import asyncio
    import threading

    from scout.config import Settings

    creds = '{"client_id": "a", "client_secret": "b", "refresh_token": "c"}'
    ad = GoogleCalendarAdapter(
        Settings(_env_file=None, cors_allowed_origins="http://x", google_oauth_credentials=creds)
    )
    seen = {}

    def grab():
        seen[threading.get_ident()] = ad._http()
        return ad._http() is ad._http()

    same_within_thread = await asyncio.gather(
        asyncio.to_thread(grab), asyncio.to_thread(grab), asyncio.to_thread(grab)
    )
    assert all(same_within_thread)
    assert len({id(h) for h in seen.values()}) == len(seen)  # one transport per thread
    assert GoogleCalendarAdapter.with_service(FakeService(), "T", "O")._http() is None


def test_lazy_build_does_not_deadlock_on_its_own_lock():
    # _service() holds the adapter lock while it asks _credentials() for the same lock. A
    # non-reentrant lock here hung the first real Gmail send (2026-09-10, route test).
    import threading

    from scout.config import Settings
    from scout.providers.gmail import GmailAdapter

    creds = '{"client_id": "a", "client_secret": "b", "refresh_token": "c"}'
    settings = Settings(
        _env_file=None, cors_allowed_origins="http://x", google_oauth_credentials=creds
    )
    for ad in (GoogleCalendarAdapter(settings), GmailAdapter(settings)):
        t = threading.Thread(target=ad._service, daemon=True)  # static discovery: no network
        t.start()
        t.join(10)
        assert not t.is_alive(), type(ad).__name__
