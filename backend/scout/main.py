"""App factory. `python -m scout.main` runs every boot check BEFORE binding the port."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scout.api.http import router as http_router
from scout.api.ws import router as ws_router
from scout.config import Settings
from scout.conversation.job1 import Job1
from scout.conversation.live import LiveSession
from scout.conversation.orchestrator import TurnOrchestrator
from scout.conversation.session import SessionManager
from scout.engines.availability import AvailabilityRegister
from scout.platform import telemetry
from scout.platform.artefacts import ArtefactStore
from scout.platform.boot import BootError, check_bundle, check_secrets, run_boot_checks
from scout.providers import make_job1_client

EXPIRY_SWEEP_S = 60


def create_app(settings: Settings) -> FastAPI:
    # Loaded once, here, and never written afterwards (arch §6.3). Under `main()` the
    # boot checks have already loaded it once; the second load is the price of a
    # store that is refused before the port is bound.
    store = ArtefactStore.load(settings.bundle_dir)
    sessions = SessionManager(settings.session_ttl_s)
    orchestrator = TurnOrchestrator(
        store,
        settings,
        job1=Job1(make_job1_client(settings), store.localities),
        job2=_job2(settings),
        availability=AvailabilityRegister(store),
        speaker_factory=lambda: None,  # every live session supplies its own (Task 2.10)
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        sweeper = asyncio.create_task(_expire_loop(sessions))
        try:
            yield
        finally:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper

    app = FastAPI(title="scout", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.sessions = sessions
    app.state.orchestrator = orchestrator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-operator-token"],
    )
    app.include_router(http_router)
    app.include_router(ws_router)
    app.state.session_factory = lambda s, sink: LiveSession(s, sink, orchestrator, sessions)
    telemetry.configure(settings.latency_log_path)
    return app


def _job2(settings: Settings):
    """Job 2 arrives in Task 2.12; until then lane B answers with a typed failure."""
    try:
        from scout.conversation.job2 import Job2
        from scout.providers.anthropic_job2 import AnthropicJob2Client

        return Job2(AnthropicJob2Client(settings))
    except ImportError:
        return None


async def _expire_loop(sessions: SessionManager) -> None:
    while True:
        await asyncio.sleep(EXPIRY_SWEEP_S)
        sessions.expire_idle()


BOOT_CHECKS = [check_secrets, check_bundle]


def main() -> None:
    settings = Settings()
    try:
        run_boot_checks(settings, BOOT_CHECKS)
    except BootError as e:
        # Railway's health check sees a dead process, not a renter.
        print(e, file=sys.stderr)
        sys.exit(2)
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port, ws_ping_interval=20)


if __name__ == "__main__":
    main()
