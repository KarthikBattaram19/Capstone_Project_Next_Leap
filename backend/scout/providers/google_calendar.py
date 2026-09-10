"""Google Calendar — bookings live here, not in a database of ours (AD-7)."""

# Signatures verified against google-api-python-client 2.200.0 and google-auth 2.57.0 on
# 2026-09-10 (python -c "import inspect, ..."):
#   googleapiclient.discovery.build(serviceName, version, http=None, ..., credentials=None,
#       cache_discovery=True, cache=None, client_options=None, ..., num_retries=1,
#       static_discovery=None, always_use_jwt_access=False)
#   google.oauth2.credentials.Credentials.__init__(self, token, refresh_token=None,
#       id_token=None, token_uri=None, client_id=None, client_secret=None, scopes=None, ...)
#   googleapiclient.errors.HttpError(resp, content, uri=None) exposes the status BOTH as
#       e.resp.status (httplib2.Response, the original) and as e.status_code (a property
#       added in later releases, reads resp.status). str(e) is
#       '<HttpError 401 when requesting <uri> returned "...". Details: "..."'
#   The auth check below reads e.resp.status, as the addendum wrote it; both agree.

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from scout.config import Settings
from scout.domain.booking import IST, Slot
from scout.platform import telemetry

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
]


class CalendarError(RuntimeError):
    """Wraps HttpError and network failures; `status` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class CalendarAuthError(CalendarError):
    pass


@dataclass(frozen=True)
class EventRef:
    calendar_id: str
    event_id: str
    start: datetime
    end: datetime
    listing_id: str
    email: str


def credentials_from(settings: Settings) -> Credentials:
    c = json.loads(settings.google_oauth_credentials)
    return Credentials(
        token=None,
        refresh_token=c["refresh_token"],
        client_id=c["client_id"],
        client_secret=c["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


class GoogleCalendarAdapter:
    def __init__(self, settings: Settings) -> None:
        # Nothing is parsed or built here. `create_app` constructs this adapter (Task 3.3)
        # and its unit tests run with empty Google credentials, so the credentials are read
        # and the service built on first use instead — once, then reused for the life of
        # the adapter (P2, connection reuse). Boot (platform/boot.py) is what guarantees the
        # credentials are present before the port opens.
        self._settings: Settings | None = settings
        self._svc = None
        self._creds: Credentials | None = None
        self._lock = threading.RLock()  # _service() holds it while calling _credentials()
        self._local = threading.local()
        self.tenant_id, self.owner_id = (
            settings.google_tenant_calendar_id,
            settings.google_owner_calendar_id,
        )

    @classmethod
    def with_service(cls, service, tenant_id: str, owner_id: str) -> GoogleCalendarAdapter:
        self = cls.__new__(cls)  # bypasses __init__: no real build() happens
        self._settings = None
        self._svc, self.tenant_id, self.owner_id = service, tenant_id, owner_id
        return self

    def _credentials(self) -> Credentials:
        if self._settings is None:
            raise CalendarError("calendar adapter has neither settings nor a service")
        with self._lock:
            if self._creds is None:
                self._creds = credentials_from(self._settings)
            return self._creds

    def _http(self) -> AuthorizedHttp | None:
        """One transport per worker thread; None when the service is a test fake.

        httplib2.Http is not thread-safe, and the two calendar writes run in parallel on
        the asyncio thread pool (P6). Sharing one transport between them corrupts each
        other's TLS records - measured 2026-09-10 against Google: 6 of 6 warm parallel
        inserts failed with SSL WRONG_VERSION_NUMBER / BAD_RECORD_MAC, which is what put
        a live booking into "reconciling". The pool reuses its threads, so each thread
        keeps its own keep-alive connection (P2 still holds).
        """
        if self._settings is None:
            return None
        h = getattr(self._local, "http", None)
        if h is None:
            h = AuthorizedHttp(self._credentials(), http=httplib2.Http(timeout=30))
            self._local.http = h
        return h

    def _exec(self, request):
        h = self._http()
        return request.execute(http=h) if h is not None else request.execute()

    def _service(self):
        if self._svc is None:
            with self._lock:
                if self._svc is None:
                    self._svc = build(
                        "calendar",
                        "v3",
                        credentials=self._credentials(),
                        cache_discovery=False,
                    )
        return self._svc

    async def _run(self, name: str, fn):
        with telemetry.span(f"external.google.{name}"):
            try:
                return await asyncio.to_thread(fn)
            except HttpError as e:
                status = e.resp.status
                if status in (401, 403):
                    raise CalendarAuthError(str(e), status) from e
                raise CalendarError(str(e), status) from e
            except Exception as e:
                raise CalendarError(str(e)) from e

    async def freebusy(
        self, calendar_id: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        body = {
            "timeMin": start.astimezone(IST).isoformat(),
            "timeMax": end.astimezone(IST).isoformat(),
            "timeZone": "Asia/Kolkata",
            "items": [{"id": calendar_id}],
        }
        res = await self._run(
            "freebusy", lambda: self._exec(self._service().freebusy().query(body=body))
        )
        busy = res["calendars"][calendar_id].get("busy", [])
        return [
            (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in busy
        ]

    async def insert(
        self,
        calendar_id: str,
        summary: str,
        description: str,
        slot: Slot,
        *,
        code: str,
        listing_id: str,
        email: str,
    ) -> str:
        body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": slot.start.astimezone(IST).isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {"dateTime": slot.end.astimezone(IST).isoformat(), "timeZone": "Asia/Kolkata"},
            "extendedProperties": {
                "private": {"confirmation_code": code, "listing_id": listing_id, "email": email}
            },
        }
        res = await self._run(
            "insert",
            lambda: self._exec(self._service().events().insert(calendarId=calendar_id, body=body)),
        )
        return res["id"]

    async def delete(self, calendar_id: str, event_id: str) -> None:
        try:
            await self._run(
                "delete",
                lambda: self._exec(
                    self._service().events().delete(calendarId=calendar_id, eventId=event_id)
                ),
            )
        except CalendarError as e:
            # Already gone is success — a retried cancel must not fail the second time.
            # Decided on the status, never on the text: the error text carries the request
            # URI, and a calendar or event id can itself contain "404".
            if e.status not in (404, 410):
                raise

    async def find_by_code(self, code: str) -> list[EventRef]:
        out: list[EventRef] = []
        for cal in (self.tenant_id, self.owner_id):
            res = await self._run(
                "list",
                # `cal=cal` binds the loop variable into the lambda.
                lambda cal=cal: self._exec(
                    self._service()
                    .events()
                    .list(
                        calendarId=cal,
                        privateExtendedProperty=f"confirmation_code={code}",
                        singleEvents=True,
                    )
                ),
            )
            for ev in res.get("items", []):
                p = ev.get("extendedProperties", {}).get("private", {})
                out.append(
                    EventRef(
                        cal,
                        ev["id"],
                        datetime.fromisoformat(ev["start"]["dateTime"]),
                        datetime.fromisoformat(ev["end"]["dateTime"]),
                        p.get("listing_id", ""),
                        p.get("email", ""),
                    )
                )
        return out
