"""Deepgram in, P3b hold, ack before any model, barge-in, runaway cap, keepalive, one reconnect."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

from scout.config import Settings
from scout.contract.outcome import Answered, Failed
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation import persona
from scout.conversation.hold import looks_unfinished
from scout.conversation.orchestrator import TurnOrchestrator
from scout.conversation.session import SessionManager
from scout.conversation.speaker import Speaker, split_sentences
from scout.conversation.state import TurnState, transition
from scout.platform import telemetry
from scout.providers.deepgram_stt import DeepgramStream, build_keyterms
from scout.providers.smallest_tts import SmallestTts

RUNAWAY_S = 30.0
AUDIO_GAP_KEEPALIVE_S = 3.0  # no frames for this long means the tab stopped sending


class LiveSession:
    def __init__(
        self, settings: Settings, sink, orchestrator: TurnOrchestrator, sessions: SessionManager
    ) -> None:
        self.s, self.sink, self.orch = settings, sink, orchestrator
        self.session = sessions.create()
        self.tts = SmallestTts(settings)
        self.state = TurnState.IDLE
        self._segments: list[str] = []
        self._confidence = 1.0  # worst segment confidence of the utterance (spec §6.20)
        self._hold: asyncio.TimerHandle | None = None
        self._turn: asyncio.Task | None = None
        self._speech_started_at: float | None = None
        self._reprompted = False
        self._reconnected = False
        self._stt_down = False  # both streams failed: say so once, keep the socket for typing
        self._keepalive: asyncio.Task | None = None
        self._last_audio_at = time.monotonic()
        self.stt = self._make_stt()

    def _make_stt(self) -> DeepgramStream:
        return DeepgramStream(
            self.s,
            build_keyterms(),  # domain terms only (spec §5.1, amended 2026-09-17)
            on_interim=self._interim,
            on_final=self._final,
            on_speech_started=self._speech_started,
            on_utterance_end=self._utterance_end,
        )

    async def start(self) -> None:
        # Per session, never on the shared orchestrator.
        self.session.speaker_factory = lambda: Speaker(self.tts, self.sink)
        await self._greet()
        try:
            await self.stt.start()
        except Exception:  # noqa: BLE001 -- raising here killed the socket, and the browser
            # showed "can't reach the service" (§6.12) for a speech outage (§6.23), with the
            # typed fallback gone too.
            await self._speech_unavailable()
            return
        self._keepalive = asyncio.create_task(self._keepalive_loop())

    async def _greet(self) -> None:
        """Nakshatra speaks first (arch §11.2 P-7), before the STT stream opens.

        A constant, never a model call, so no provider sits on the path to the first sound
        the renter hears. It travels as an ordinary `answered` outcome (addendum Task 2.10)
        and is spoken in the background, like every other reply.
        """
        greeting = Answered(
            view_model=AnsweredViewModel(notices=[persona.GREETING]), spoken=persona.GREETING
        )
        await self.sink.outcome({"outcome": greeting.model_dump()})
        self.session.speaker = self.session.speaker_factory()
        self.session.speaking = asyncio.create_task(
            self.session.speaker.speak(split_sentences(persona.GREETING))
        )

    async def close(self) -> None:
        if self._keepalive:
            self._keepalive.cancel()
        if self._stt_down:
            with contextlib.suppress(Exception):  # a stream that never opened cannot close
                await self.stt.close()
            return
        await self.stt.close()

    async def audio(self, pcm: bytes) -> None:
        if self._stt_down:
            return  # the mic keeps streaming; the renter has already been told to type
        self._last_audio_at = time.monotonic()
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
            self._log_barge_in("typed")
            await self.orch.cancel_speech(self.session)
            if self._turn and not self._turn.done():
                self._turn.cancel()
        if self.state is not TurnState.CAPTURING:
            self.state = transition(self.state, TurnState.CAPTURING)
        await self._finalize()

    async def stop(self) -> None:
        """The page's Stop control (contract StopIn, D2 2026-09-17): stop the rest of the reply.

        The page has already stopped playing and un-muted the mic. SPEAKING is a turn's reply;
        IDLE covers the greeting, which is spoken without leaving IDLE, and a reply the server
        has finished sending while the page still plays it. Any other state is the renter's
        next sentence already in flight, and a late tap must not cancel that turn.
        """
        if self.state in (TurnState.SPEAKING, TurnState.IDLE):
            self._log_barge_in("stop")
            await self.orch.cancel_speech(self.session)
            return
        # A "why this one?" answer is spoken while Job 2 is still writing it, so the long
        # replies Stop exists for are mostly heard in TYPE_B (batch review, 2026-09-17). Only
        # the speech stops: the turn runs on and its explanation still reaches the screen.
        speaking = getattr(self.session, "speaking", None)
        speaker = getattr(self.session, "speaker", None)
        if self.state is TurnState.TYPE_B and speaker and speaking and not speaking.done():
            self._log_barge_in("stop")
            await speaker.cancel()

    def _keepalive_due(self) -> bool:
        """IDLE and SPEAKING as before, and ANY state once no frame has flowed for a while.

        A hidden tab stops the frames (§6.16). A sound onset with no words had left the
        session CAPTURING, where no keepalive went out, so Deepgram closed the idle stream
        and the renter returned to "I lost the connection" having said nothing (production,
        2026-09-17).
        """
        if self.state in (TurnState.IDLE, TurnState.SPEAKING):
            return True
        return time.monotonic() - self._last_audio_at >= AUDIO_GAP_KEEPALIVE_S

    async def _keepalive_loop(self) -> None:
        while True:
            # Deepgram closes a stream after ~10 s with no audio (net0001); checking every
            # 2 s puts the first keepalive of a gap at most 5 s in.
            await asyncio.sleep(2)
            if self._keepalive_due():
                # A missed keepalive is not a turn failure: the next send_audio finds the
                # stream gone and takes the one permitted reconnect.
                with contextlib.suppress(Exception):
                    await self.stt.keepalive()

    # ---- Deepgram callbacks

    async def _speech_started(self) -> None:
        if self.state is TurnState.IDLE:
            self.state = transition(self.state, TurnState.CAPTURING)
        # While SPEAKING, a sound onset alone stops nothing either (D1, production
        # 2026-09-17): five replies were stopped 0.9-1.3 s after the renter's last words,
        # with no TTS bytes sent and no renter words for 5-9 s after. Likely cause, not
        # confirmed: the server is SPEAKING from the moment the outcome is sent, before the
        # page has muted the mic, so a trailing noise's onset landed in that window. Barge-in
        # during SPEAKING (spec §6.17) is words, in _words_arrived, or typing, in text().
        # While the assistant is still THINKING, a sound onset alone cancels nothing.
        # Deepgram's VAD fires on a breath or a chair; cancelling the turn on it and then
        # hearing no words left the page in "processing" forever (production, 2026-09-10).
        # Words arriving during a thinking turn are the barge-in, below.
        # The runaway clock (§6.19) is NOT started here: a sound with no words behind it
        # left it running, and 35 s later the renter's first frame capped an empty
        # utterance - "I didn't hear anything" mid-sentence (production, 2026-09-17).

    def _start_runaway_clock(self, text: str) -> None:
        """§6.19 measures an utterance, so its clock starts at the first words."""
        if text.strip():
            self._speech_started_at = self._speech_started_at or time.monotonic()

    _THINKING = frozenset(
        {
            TurnState.TRANSCRIBING,
            TurnState.ACK,
            TurnState.CLASSIFYING,
            TurnState.TYPE_A,
            TurnState.TYPE_B,
        }
    )

    def _log_barge_in(self, trigger: str) -> None:
        """One line per barge-in: what triggered it and the state it interrupted. No
        transcript text — logs never carry what the renter said (spec §3.2, §5.3)."""
        print(f"barge-in trigger={trigger} state={self.state.value.lower()}", file=sys.stderr)

    async def _barge_in(self, trigger: str) -> None:
        self._log_barge_in(trigger)
        await self.orch.cancel_speech(self.session)
        if self._turn and not self._turn.done():
            self._turn.cancel()
        self.state = transition(self.state, TurnState.CAPTURING)

    async def _words_arrived(self, text: str) -> None:
        """Real words during a thinking or speaking turn: the renter's new sentence wins."""
        if text.strip() and self.state in self._THINKING | {TurnState.SPEAKING}:
            await self._barge_in("words")

    async def _interim(self, text: str) -> None:
        await self._words_arrived(text)
        self._start_runaway_clock(text)
        if self.state is TurnState.IDLE:
            self.state = transition(self.state, TurnState.CAPTURING)
        await self.sink.transcript(" ".join([*self._segments, text]), final=False)  # L0

    async def _final(self, text: str, confidence: float = 1.0) -> None:
        """`confidence` is Deepgram's, for spec §6.20. It defaults to 1.0 so a typed message
        and a test that drives this directly are never treated as noisy speech."""
        await self._words_arrived(text)
        self._start_runaway_clock(text)
        if self.state is TurnState.IDLE:
            self.state = transition(self.state, TurnState.CAPTURING)
        self._segments.append(text)
        # The utterance is as trustworthy as its worst segment, matching DeepgramStream.
        self._confidence = min(self._confidence, confidence)
        if self._hold:
            self._hold.cancel()
        if looks_unfinished(" ".join(self._segments)):  # P3b: wait up to 400 ms more
            loop = asyncio.get_running_loop()
            self._hold = loop.call_later(
                self.s.hold_extra_ms / 1000, lambda: asyncio.create_task(self._finalize())
            )
        else:
            await self._finalize()

    async def _utterance_end(self) -> None:  # hard stop (~1.5 s)
        if self._segments:
            await self._finalize()

    async def _finalize(self) -> None:
        if self._hold:
            self._hold.cancel()
            self._hold = None
        text = " ".join(self._segments).strip()
        confidence = self._confidence
        self._segments = []
        self._confidence = 1.0
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

        final_at = time.perf_counter()  # end-of-speech: the turn's clock starts here
        self.state = transition(self.state, TurnState.TRANSCRIBING)
        await self.sink.transcript(text, final=True)

        self.state = transition(self.state, TurnState.ACK)
        await self.sink.ack(text)  # L1 — before any model call
        ack_at = time.perf_counter()

        self.state = transition(self.state, TurnState.CLASSIFYING)
        self._turn = asyncio.create_task(self._run_turn(text, final_at, ack_at, confidence))

    async def _run_turn(
        self,
        text: str,
        final_at: float | None = None,
        ack_at: float | None = None,
        confidence: float = 1.0,
    ) -> None:
        from scout.conversation.router import classify_turn

        tt = classify_turn(text, has_shortlist=not self.session.shortlist.is_empty())
        self.state = transition(self.state, TurnState.TYPE_B if tt == "B" else TurnState.TYPE_A)
        with telemetry.trace(turn_type=tt, t0=final_at) as tr:
            # Both happened before this task existed, so outside any trace; placed now.
            if final_at is not None and ack_at is not None:
                tr.mark_at(telemetry.STT_FINAL, final_at)
                tr.mark_at(telemetry.ACK, ack_at)
            try:
                outcome = await self.orch.handle_text(self.session, text, confidence)
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
            await self._speech_unavailable()
            return
        self._reconnected = True  # the one permitted reconnect
        lost = " ".join(self._segments)
        self._segments = []
        self._confidence = 1.0
        self.stt = self._make_stt()
        try:
            await self.stt.start()
        except Exception:  # noqa: BLE001 -- an unguarded failure here escaped audio() and
            # closed the socket (found by the Task 4.2 fault switch's Deepgram path).
            await self._speech_unavailable()
            return
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

    async def _speech_unavailable(self) -> None:
        if self._stt_down:
            return  # told once; every later mic frame would otherwise repeat it
        self._stt_down = True
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
