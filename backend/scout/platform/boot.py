"""Fail at start-up, never mid-sentence (arch §12.3). Every check runs; every failure is listed."""

from __future__ import annotations

from collections.abc import Callable

from scout.config import Settings


class BootError(RuntimeError):
    pass


BootCheck = Callable[[Settings], None]

# Environment-variable name -> Settings attribute. The names on the left are what an
# operator sets, so they are what a failure message must say; `.env.example` lists
# exactly these nine.
REQUIRED: dict[str, str] = {
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "GROQ_API_KEY": "groq_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "SMALLEST_API_KEY": "smallest_api_key",
    "GOOGLE_OAUTH_CREDENTIALS": "google_oauth_credentials",
    "GOOGLE_TENANT_CALENDAR_ID": "google_tenant_calendar_id",
    "GOOGLE_OWNER_CALENDAR_ID": "google_owner_calendar_id",
    "GOOGLE_SENDER_EMAIL": "google_sender_email",
    "OPERATOR_TOKEN": "operator_token",
}


def check_secrets(s: Settings) -> None:
    missing = [env for env, attr in REQUIRED.items() if not getattr(s, attr)]
    if missing:
        raise BootError("missing required environment variables: " + ", ".join(missing))
    # A wildcard origin would let any page open a socket to this backend; an empty
    # list means the real frontend cannot. Neither is a working deployment.
    if not s.origins or any(o == "*" for o in s.origins):
        raise BootError("CORS_ALLOWED_ORIGINS must be an explicit allowlist, never '*' or empty")


def run_boot_checks(s: Settings, checks: list[BootCheck]) -> None:
    failures: list[str] = []
    for check in checks:
        try:
            check(s)
        except BootError as e:
            # Collected, not raised: an operator missing two things is told both at
            # once rather than one per restart.
            failures.append(str(e))
    if failures:
        raise BootError("boot check failed:\n  - " + "\n  - ".join(failures))
