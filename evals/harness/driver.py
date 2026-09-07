"""Drives the orchestrator directly: text in, TurnOutcome out. No audio (AD-6)."""

from __future__ import annotations

from scout.config import Settings
from scout.contract.outcome import TurnOutcome
from scout.platform.artefacts import ArtefactStore


class Driver:
    def __init__(self, store: ArtefactStore, settings: Settings) -> None:
        self.store, self.settings = store, settings

    async def run(self, turns: list[str], *, session=None) -> list[TurnOutcome]:
        # Both exist from Task 2.10; until then the import fails and the suites xfail.
        from scout.conversation.orchestrator import TurnOrchestrator
        from scout.conversation.session import SessionManager

        orch = TurnOrchestrator.for_evals(self.store, self.settings)
        session = session or SessionManager(ttl_s=600).create()
        # One outcome per text turn, all on the same session.
        return [await orch.handle_text(session, t) for t in turns]
