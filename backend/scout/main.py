"""App factory. `python -m scout.main` runs every boot check BEFORE binding the port."""

from __future__ import annotations

import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scout.api.http import router as http_router
from scout.api.ws import router as ws_router
from scout.config import Settings
from scout.conversation.stub_turn import StubSession
from scout.platform import telemetry
from scout.platform.artefacts import ArtefactStore
from scout.platform.boot import BootError, check_bundle, check_secrets, run_boot_checks


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="scout", docs_url=None, redoc_url=None)
    app.state.settings = settings
    # Loaded once, here, and never written afterwards (arch §6.3). Under `main()` the
    # boot checks have already loaded it once; the second load is the price of a
    # store that is refused before the port is bound.
    app.state.store = ArtefactStore.load(settings.bundle_dir)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-operator-token"],
    )
    app.include_router(http_router)
    app.include_router(ws_router)
    app.state.session_factory = StubSession
    telemetry.configure(settings.latency_log_path)
    return app


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
