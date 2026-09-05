"""App factory. `python -m scout.main` runs every boot check BEFORE binding the port."""

from __future__ import annotations

import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scout.api.http import router as http_router
from scout.config import Settings
from scout.platform import telemetry
from scout.platform.boot import BootError, check_secrets, run_boot_checks


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="scout", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-operator-token"],
    )
    app.include_router(http_router)
    telemetry.configure(settings.latency_log_path)
    return app


BOOT_CHECKS = [check_secrets]  # Task 1.4 appends the bundle checks


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
