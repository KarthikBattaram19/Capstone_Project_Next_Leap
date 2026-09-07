"""Fail at start-up, never mid-sentence (arch §12.3). Every check runs; every failure is listed."""

from __future__ import annotations

from collections.abc import Callable

from scout.config import ENV_FILE, Settings


class BootError(RuntimeError):
    pass


BootCheck = Callable[[Settings], None]

# Environment-variable name -> Settings attribute. The names on the left are what an
# operator sets, so they are what a failure message must say; `.env.example` lists
# every one of these ten, and a test asserts it still does.
#
# SMALLEST_VOICE_ID belongs here even though it is an id, not a secret. Without it
# Smallest.ai answers 400 "Voice '' is not available on the lightning_v3.1_pro
# model", so the process boots, passes its healthcheck and looks entirely healthy
# while being unable to speak a single word. That is exactly how the silent-turn
# defect reached production: a required value that fails only mid-sentence must
# fail at start-up instead (arch 12.3).
REQUIRED: dict[str, str] = {
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "GROQ_API_KEY": "groq_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "SMALLEST_API_KEY": "smallest_api_key",
    "SMALLEST_VOICE_ID": "smallest_voice_id",
    "GOOGLE_OAUTH_CREDENTIALS": "google_oauth_credentials",
    "GOOGLE_TENANT_CALENDAR_ID": "google_tenant_calendar_id",
    "GOOGLE_OWNER_CALENDAR_ID": "google_owner_calendar_id",
    "GOOGLE_SENDER_EMAIL": "google_sender_email",
    "OPERATOR_TOKEN": "operator_token",
}


def check_secrets(s: Settings) -> None:
    missing = [env for env, attr in REQUIRED.items() if not getattr(s, attr)]
    if missing:
        # Name the file that was consulted. Without this, "secrets missing" reads the
        # same whether the operator forgot a value or put the file somewhere else.
        state = "present" if ENV_FILE.exists() else "NOT FOUND"
        raise BootError(
            f"missing required environment variables: {', '.join(missing)}\n"
            f"    read from the environment and {ENV_FILE} ({state})\n"
            f"    copy .env.example to {ENV_FILE} and fill it in"
        )
    # A wildcard origin would let any page open a socket to this backend; an empty
    # list means the real frontend cannot. Neither is a working deployment.
    if not s.origins or any(o == "*" for o in s.origins):
        raise BootError("CORS_ALLOWED_ORIGINS must be an explicit allowlist, never '*' or empty")


def check_bundle(s: Settings) -> None:
    # Local import: avoids chroma at import time (and a circular import, since the
    # store raises BootError from this module).
    from scout.platform.artefacts import ArtefactStore

    # Raises BootError with the specific reason: unreadable file, contract_version,
    # listing count, OSM coverage, embedding fingerprint, or a locality with no
    # collection.
    ArtefactStore.load(s.bundle_dir)


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
