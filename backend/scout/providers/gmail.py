"""Gmail — sends the PDF, which is then discarded. Nothing retained (spec §2.5)."""

# googleapiclient.discovery.build signature verified against google-api-python-client
# 2.200.0 on 2026-09-10; see the note at the top of scout/providers/google_calendar.py.

from __future__ import annotations

import asyncio
import base64
import threading
from email.message import EmailMessage

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from scout.config import Settings
from scout.platform import telemetry
from scout.providers.google_calendar import credentials_from


class MailError(RuntimeError):
    pass


class GmailAdapter:
    def __init__(self, settings: Settings) -> None:
        # Same lazy pattern as GoogleCalendarAdapter: `create_app` constructs this with
        # whatever credentials are present, so nothing is parsed or built until the first
        # send. One service, built once, reused (P2).
        self._settings: Settings | None = settings
        self._svc = None
        self._creds = None
        self._lock = threading.RLock()  # _service() holds it while calling _credentials()
        self._local = threading.local()
        self._from = settings.google_sender_email

    @classmethod
    def with_service(cls, service, sender: str) -> GmailAdapter:
        self = cls.__new__(cls)  # bypasses __init__: no real build() happens
        self._settings = None
        self._svc, self._from = service, sender
        return self

    def _credentials(self):
        if self._settings is None:
            raise MailError("mail adapter has neither settings nor a service")
        with self._lock:
            if self._creds is None:
                self._creds = credentials_from(self._settings)
            return self._creds

    def _http(self) -> AuthorizedHttp | None:
        # One transport per worker thread (httplib2.Http is not thread-safe); see
        # GoogleCalendarAdapter._http for the measurement. None for a test fake.
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
                        "gmail", "v1", credentials=self._credentials(), cache_discovery=False
                    )
        return self._svc

    async def send_pdf(
        self, to: str, subject: str, body: str, pdf_bytes: bytes, filename: str
    ) -> str:
        msg = EmailMessage()
        msg["To"], msg["From"], msg["Subject"] = to, self._from, subject
        msg.set_content(body)
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        with telemetry.span("external.gmail.send"):
            try:
                res = await asyncio.to_thread(
                    lambda: self._exec(
                        self._service().users().messages().send(userId="me", body={"raw": raw})
                    )
                )
            except Exception as e:
                raise MailError(str(e)) from e
        return res["id"]
