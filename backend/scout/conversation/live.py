"""Deepgram in, P3b hold, ack before any model, barge-in, runaway cap, keepalive, one reconnect."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

from scout.config import Settings
from scout.contract.outcome import Failed
from scout.conversation.hold import looks_unfinished
from scout.conversation.orchestrator import TurnOrchestrator
from scout.conversation.session import SessionManager
from scout.conversation.speaker import Speaker
from scout.conversation.state import TurnState, transition
from scout.platform import telemetry
from scout.providers.deepgram_stt import DeepgramStream, build_keyterms
from scout.providers.smallest_tts import SmallestTts

RUNAWAY_S = 30.0


class LiveSession:
    def __init__(
        self, settings: Settings, sink, orchestrator: TurnOrchestrator, sessions: SessionManager
    ) -> None:
        self.s, self.sink, self.orch = settings, sink, orchestrator
        self.session = sessions.create()
        self.tts = SmallestTts(settings)
        self.state = TurnState.IDLE
        self._segments: list[str] = []
        self._hold: asyncio.TimerHandle | None = None
        self._turn: asyncio.Task | None = None
        self._speech_started_at: float | None = None
        self._reprompted = False
        self._reconnected = False
        self._keepalive: asyncio.Task | None = None
        self.stt = self._make_stt()

    def _make_stt(self) -> DeepgramStream:
        return DeepgramStream(
            self.s,
            build_keyterms(self.orch.store.localities),
            on_interim=self._interim,
            on_final=self._final,
            on_speech_started=self._speech_started,
            on_utterance_end=self._utterance_end,
        )

    async def start(self) -> None:
        await self.stt.start()
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        # Per session, never on the shared orchestrator.
        self.session.speaker_factory = lambda: Speaker(self.tts, self.sink)

    async def close(self) -> None:
        if self._keepalive:
            self._keepalive.cancel()
        await self.stt.close()

    async def audio(self, pcm: bytes) -> None:
        try:
            await self.stt.send_audio(pcm)
        except Exception:  # noqa: BLE001 -- any transport error is a lost stream (spec §6.23)
            await self._stt_lost()
        if (
            self._speech_started_at is not None
            and time.monotonic() - self._speech_started_at > RUNAWAY_S
            and self.state is TurnState.CAPTURING
        ):
            await self._finalize()  # runaway cap (spec §6.19)

    async def text(self, text: str) -> None:
        """Typed fallback (spec §6.13).

        The state hop is load-bearing: a typed message arrives from IDLE — nobody has
        spoken — and `_finalize` returns immediately unless the state is CAPTURING. Without
        it the fallback silently does nothing, and it is the recovery path for a denied
        microphone, a lost device and a second Deepgram failure (eval.md EC-WS-07).
        """
        self._segments = [text]
        if self.state is TurnState.SPEAKING:  # typing is barge-in too
            await self.orch.cancel_speech(self.session)
            if self._turn and not self._turn.done():
                self._turn.cancel()
        if self.state is not TurnState.CAPTURING:
            self.state = transition(self.state, TurnState.CAPTURING)
        await self._finalize()

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.state in (TurnState.IDLE, TurnState.SPEAKING):
                # A missed keepalive is not a turn failure: the next send_audio finds the
                # stream gone and takes the one permitted reconnect.
                with contextlib.suppress(Exception):
                    await self.stt.keepalive()

    # ---- Deepgram callbacks

    async def _speech_started(self) -> None:
        if self.state is TurnState.IDLE:
            self.state = transition(self.state, TurnState.CAPTURING)
        elif self.state is not TurnState.CAPTURING:
            # Barge-in (spec §6.17). The renter's new sentence always wins, whether the
            # assistant was speaking or still thinking.
            await self.orch.cancel_speech(self.session)
            if self._turn and not self._turn.done():
                self._turn.cancel()
            self.state = transition(self.state, TurnState.CAPTURING)
        self._speech_started_at = self._speech_started_at or time.monotonic()

    async def _interim(self, text: str) -> None:
        if self.state is TurnState.IDLE:
            self.state = transition(self.state, TurnState.CAPTURING)
        await self.sink.transcript(" ".join([*self._segments, text]), final=False)  # L0

    async def _final(self, text: str) -> None:
        self._segments.append(text)
        if self._hold:
            self._hold.cancel()
        if looks_unfinished(" ".join(self._segments)):  # P3b: wait up to 400 ms more
            loop = asyncio.get_running_loop()
            self._hold = loop.call_later(
                self.s.hold_extra_ms / 1000, lambda: asyncio.create_task(self._finalize())
            )
        else:
            await self._finalize()

    async def _utterance_end(self) -> None:  # hard stop (~1 s)
        if self._segments:
            await self._finalize()

    async def _finalize(self) -> None:
        if self._hold:
            self._hold.cancel()
            self._hold = None
        text = " ".join(self._segments).strip()
        self._segments = []
        self._speech_started_at = None
        if self.state is not TurnState.CAPTURING:
            return

        if not text:  # silence / no words (spec §6.18)
            self.state = TurnState.IDLE
            if not self._reprompted:
                self._reprompted = True
                await self.sink.outcome(
                    {
                        "outcome": Failed(
                            capability="speech_in",
                            tell_renter=(
                                "I didn't hear any words. Try: 'a 2BHK in Koramangala "
                                "under 35,000'."
                            ),
                            retry_worth_it=True,
                            spoken=(
                                "I didn't hear anything — try 'a 2BHK in Koramangala under 35,000'."
                            ),
                        ).model_dump()
                    }
                )
            return

        # The re-prompt suppressor covers a RUN of silences, not the whole session: cleared
        # here, on the first utterance that carries words, so a renter who goes quiet again
        # later is answered again instead of meeting silence (eval.md EC-WS-14).
        self._reprompted = False

        self.state = transition(self.state, TurnState.TRANSCRIBING)
        await self.sink.transcript(text, final=True)

        self.state = transition(self.state, TurnState.ACK)
        await self.sink.ack(text)  # L1 — before any model call
        telemetry.mark(telemetry.ACK)

        self.state = transition(self.state, TurnState.CLASSIFYING)
        self._turn = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str) -> None:
        from scout.conversation.router import classify_turn

        tt = classify_turn(text, has_shortlist=not self.session.shortlist.is_empty())
        self.state = transition(self.state, TurnState.TYPE_B if tt == "B" else TurnState.TYPE_A)
        with telemetry.trace(turn_type=tt):
            try:
                outcome = await self.orch.handle_text(self.session, text)
            except asyncio.CancelledError:
                return  # barge-in cancelled the turn
            except Exception as e:  # noqa: BLE001 -- a turn runs as a task nobody awaits, so
                # without this the event loop swallows the exception and the browser is left
                # after `audio_out start` with no chunks, no end and no outcome — silence
                # that looks like a hang. Type only: a provider's message can quote the
                # utterance back, and logs carry no transcript text (spec §3.2, §5.3).
                print(f"turn failed ({tt}): {type(e).__name__}", file=sys.stderr)
                await self._report_turn_failure()
                return

            if self.state not in (TurnState.TYPE_A, TurnState.TYPE_B):
                return  # the renter interrupted while this turn was thinking

            self.state = transition(self.state, TurnState.SPEAKING)
            await self.sink.outcome({"outcome": outcome.model_dump()})  # L4 / L5
            telemetry.mark(
                telemetry.SHORTLIST_RENDERED if tt == "A" else telemetry.EXPLANATION_RENDERED
            )
            speaking = getattr(self.session, "speaking", None)
            if speaking:
                try:
                    await speaking
                except asyncio.CancelledError:
                    pass
            if self.state is TurnState.SPEAKING:
                self.state = transition(self.state, TurnState.IDLE)

    async def _report_turn_failure(self) -> None:
        msg = "Something went wrong on my side. Please say that again."
        await self.sink.outcome(
            {
                "outcome": Failed(
                    capability="understanding",
                    tell_renter=msg,
                    retry_worth_it=True,
                    spoken=msg,
                ).model_dump()
            }
        )
        self.state = TurnState.IDLE

    async def _stt_lost(self) -> None:  # spec §6.23
        if self._reconnected:
            await self.sink.outcome(
                {
                    "outcome": Failed(
                        capability="speech_in",
                        tell_renter=(
                            "Speech recognition is unavailable right now. You can type instead."
                        ),
                        retry_worth_it=True,
                        spoken="Speech recognition is unavailable right now.",
                    ).model_dump()
                }
            )
            return
        self._reconnected = True  # the one permitted reconnect
        lost = " ".join(self._segments)
        self._segments = []
        self.stt = self._make_stt()
        await self.stt.start()
        await self.sink.outcome(
            {
                "outcome": Failed(
                    capability="speech_in",
                    tell_renter=(
                        "I lost the connection mid-sentence"
                        + (f" after: {lost}" if lost else "")
                        + ". Please say it again."
                    ),
                    retry_worth_it=True,
                    spoken="I lost the connection for a moment — please say that again.",
                ).model_dump()
            }
        )
