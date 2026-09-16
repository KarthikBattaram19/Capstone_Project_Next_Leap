"""The only part that knows the whole turn (arch §6.1). Lane A answers, lane B explains."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from scout.config import Settings
from scout.contract.outcome import Answered, Degraded, Empty, Failed, NeedsInput, TurnOutcome
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation.booking_flow import BookingFlow, BookingNotWired
from scout.conversation.job1 import Job1, Job1Down, Job1Result
from scout.conversation.router import classify_turn, parse_ordinal
from scout.conversation.session import ConfirmConstraints, ConfirmHeard, ConfirmLocality, Session
from scout.conversation.speaker import Speaker, split_sentences
from scout.domain.constraints import ConstraintEdit
from scout.domain.money import rupees
from scout.domain.shortlist import Shortlist
from scout.engines import shortlist as engine
from scout.engines.availability import AvailabilityRegister
from scout.engines.commute import CommuteService
from scout.engines.reducer import Contradiction, apply_edits, confirm_all
from scout.platform import telemetry
from scout.platform.artefacts import ArtefactStore
from scout.presentation.viewmodel import ViewModelBuilder
from scout.providers import make_job1_client

# Every fixed conversational line this file speaks, in one place. The branches below read
# their wording from here rather than inlining a string, so the sentence-cap assertion in
# test_persona.py cannot be bypassed by adding a reply somewhere else.
#
# What the cap does not govern: the shortlist reading and the Type B explanation are built
# from however many facts resolved, and their length is set by the data, not the persona
# (arch §11.2). They are deliberately not in here.
CONVERSATIONAL_REPLIES: dict[str, str] = {
    "out_of_scope": (
        "I only help with renting a flat in Bengaluru — not buying, PGs, roommates or "
        "other cities. What are you looking for?"
    ),
    "owner_contact": (
        "The only contact I hold is the demo placeholder 999999999 — no real owner details "
        "exist in this system."
    ),
    "confirm_heard": (
        # Spec §6.20: read back what was actually heard, so a noisy transcript is confirmed
        # rather than acted on. Quoting it is the point - paraphrasing would hide the noise.
        'I heard "{heard}" — is that right?'
    ),
    "heard_wrong": "Sorry — could you say that again?",
    # Spec §6.25: English is the whole scope, and saying so beats guessing at another language.
    "english_only": (
        "I can only help in English for now. Could you say that in English — for example, "
        "'a 2BHK in Koramangala under 35,000'?"
    ),
    "english_only_locality": "I can only help in English for now. Did you mean {localities}?",
    "locality_in_english": "Okay. Which locality would you like? Please say it in English.",
    "no_constraints": (
        "Tell me a budget and a locality to start — for example, 'a 2BHK in Koramangala "
        "under 35,000'."
    ),
    "what_should_i_change": "What should I change?",
    "which_listing": "Which listing do you mean? Say the locality and rent.",
    "readback": "Just to confirm — {readback}. Is that right?",
    "provisional_notice": (
        "Proceeding on the constraints you confirmed; these are provisional — unknown: "
    ),
    "all_withdrawn": (
        "Every listing in your shortlist is no longer available. Let's start again — what "
        "are you looking for?"
    ),
}


class NullSpeaker:
    async def speak(self, sentences) -> None:
        return None

    async def cancel(self) -> None:
        return None


class TurnOrchestrator:
    def __init__(
        self,
        store: ArtefactStore,
        settings: Settings,
        *,
        job1,
        job2,
        availability: AvailabilityRegister,
        speaker_factory: Callable[[], Speaker | NullSpeaker],
        booking_flow: BookingFlow | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.job1 = job1
        self.job2 = job2
        self.availability = availability
        self.commute = CommuteService(store)
        self.vm = ViewModelBuilder(store, self.commute)
        self.speaker_factory = speaker_factory
        self.booking_flow = booking_flow or BookingNotWired()

    @classmethod
    def for_evals(cls, store: ArtefactStore, settings: Settings) -> "TurnOrchestrator":  # noqa: UP037
        try:
            from scout.conversation.job2 import Job2  # Task 2.12
            from scout.providers.anthropic_job2 import AnthropicJob2Client

            job2 = Job2(AnthropicJob2Client(settings))
        except ImportError:  # Suites A and B run before Job 2 exists
            job2 = None
        return cls(
            store,
            settings,
            job1=Job1(make_job1_client(settings), store.localities),
            job2=job2,
            availability=AvailabilityRegister(store),
            speaker_factory=lambda: NullSpeaker(),
        )

    # ---- public

    async def handle_text(
        self, session: Session, text: str, confidence: float = 1.0
    ) -> TurnOutcome:
        """`confidence` is Deepgram's for the utterance (spec §6.20); 1.0 for typed input.

        The low-confidence check is here rather than in LiveSession because the orchestrator
        owns `session.pending`, and it runs BEFORE Job 1 so a noisy utterance costs no model
        call - which matters on a 500-call day.
        """
        session.touch()
        if self._too_noisy(session, text, confidence):
            session.pending = ConfirmHeard(text)
            q = CONVERSATIONAL_REPLIES["confirm_heard"].format(heard=text)
            return NeedsInput(question=q, field="heard", options=["yes", "no"], spoken=q)
        turn_type = classify_turn(text, has_shortlist=not session.shortlist.is_empty())
        if telemetry.current() is None:
            with telemetry.trace(turn_type=turn_type):
                return await self._dispatch(session, text, turn_type)
        return await self._dispatch(session, text, turn_type)

    def _too_noisy(self, session: Session, text: str, confidence: float) -> bool:
        """Spec §6.20. Not applied to an answer we are already waiting on: a one-word "yes"
        scores low on its own, and re-asking it would loop the renter forever."""
        threshold = self.settings.stt_min_confidence
        if threshold <= 0 or confidence >= threshold or not text.strip():
            return False
        return session.pending is None

    async def aclose(self) -> None:
        """Close the provider clients on the loop that used them (app shutdown, eval run)."""
        for obj in (getattr(self.job1, "client", None), self.job2):
            close = getattr(obj, "aclose", None)
            if close is not None:
                await close()

    async def cancel_speech(self, session: Session) -> None:
        sp = getattr(session, "speaker", None)
        if sp:
            await sp.cancel()
        task = getattr(session, "job2_task", None)
        if task and not task.done():
            task.cancel()

    # ---- lanes

    async def _dispatch(self, session: Session, text: str, turn_type: str) -> TurnOutcome:
        async with session.lock:  # one lock per session
            if turn_type == "B":
                outcome = await self._lane_b(session, text)
            else:
                outcome = await self._lane_a(session, text)
            self._speak_later(session, outcome)
            return outcome

    def _speak_later(self, session: Session, outcome: TurnOutcome) -> None:
        if getattr(outcome, "_already_spoken", False):
            return
        session.speaker = (session.speaker_factory or self.speaker_factory)()
        # Speech is a background task: the result returns without waiting for audio.
        session.speaking = asyncio.create_task(
            session.speaker.speak(split_sentences(outcome.spoken))
        )

    async def _lane_b(self, session: Session, text: str) -> TurnOutcome:
        from scout.contract.viewmodels import ClaimVM, ExplanationVM, SnapshotVM
        from scout.conversation.job2 import Job2Down
        from scout.grounding.assembler import ClaimAssembler
        from scout.grounding.opener import build_opener
        from scout.grounding.resolvers import ResolverRegistry
        from scout.grounding.retrieval import Retrieval

        if self.job2 is None:
            msg = "I can't explain this one right now."
            return Failed(
                capability="explanation", tell_renter=msg, retry_worth_it=True, spoken=msg
            )

        # The ordinal is read HERE, not by Job 1: lane B never calls Job 1, so
        # Job1Result.reference does not exist on this path. "Why did you pick the second
        # one?" routes here on the word "why", and without this it would explain whichever
        # listing happened to be in focus (eval.md EC-J1-14).
        heard = session.last_read_order
        n = parse_ordinal(text)
        if n is not None and 1 <= n <= len(heard):
            lid = heard[n - 1]
            session.focus_listing_id = lid
        elif n is not None:
            return NeedsInput(
                question=CONVERSATIONAL_REPLIES["which_listing"],
                field="reference",
                spoken="Which one do you mean?",
            )
        else:
            lid = session.focus_listing_id or (heard[0] if heard else None)
            if lid is None:
                return NeedsInput(
                    question="Which listing do you mean?",
                    field="reference",
                    spoken="Which listing do you mean?",
                )
            # Falling back to the first one they heard still fixes the focus: "book it" in
            # the next breath has to mean the listing just explained.
            session.focus_listing_id = lid

        registry = ResolverRegistry(self.store, self.commute, Retrieval(self.store))
        commute_point = session.constraints.commute
        bundle = registry.resolve(lid, text, commute_point)
        opener = build_opener(bundle, commute_point.name if commute_point else None)
        assembler = ClaimAssembler(bundle)

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        await queue.put(opener)  # P8: sound before Job 2's first token

        async def sentences():
            while True:
                s = await queue.get()
                if s is None:
                    return
                yield s

        session.speaker = (session.speaker_factory or self.speaker_factory)()
        session.speaking = asyncio.create_task(session.speaker.speak(sentences()))

        claims: list[ClaimVM] = []
        bound_facts: dict = {}
        job2_failed = False
        job2_why = ""
        try:
            session.job2_task = asyncio.current_task()
            async for s in self.job2.explain(bundle, text):
                claim = assembler.bind(s)
                if claim is None:
                    continue  # dropped: no resolvable citation
                claims.append(ClaimVM(text=claim.text, citation_refs=claim.refs))
                bound_facts.update(claim.facts)
                await queue.put(claim.text)  # released only once its citation resolved
        except Job2Down as e:
            job2_failed = True
            # The provider's own words (status and message, never prose, never a key: the
            # Gemini and Anthropic errors both redact). Silent on 2026-09-14, a revoked
            # Anthropic key degraded all 20 Suite C cases and the log showed only the
            # assertions that followed.
            job2_why = str(e)[:300]
            print(f"job2 down: {job2_why}", file=sys.stderr)
        finally:
            await queue.put(None)  # the speaker's generator terminates

        session.job2_bound += assembler.bound
        for reason, n in assembler.drops.items():
            session.job2_drops[reason] = session.job2_drops.get(reason, 0) + n
        if assembler.dropped:
            # Counts and reasons only — never the sentence, which is model prose about a
            # renter's listing (spec §5.3). This is the number Docs/JOB2_SCORES.md asks for.
            print(
                f"job2 assembler: {assembler.bound} bound, {assembler.dropped} dropped "
                f"({', '.join(f'{k}={v}' for k, v in assembler.drops.items() if v)})",
                file=sys.stderr,
            )

        gaps = assembler.render_gaps() + [g for g in getattr(self.job2, "last_gaps", []) if g]
        sources = [self.vm.citation(f, lid) for f in bound_facts.values()]
        vm = self._view(session)

        if job2_failed:
            vm.notices = [
                "I can't explain this one right now — the explanation service is unavailable."
            ]
            out: TurnOutcome = Degraded(
                view_model=vm,
                missing=["explanation"],
                why=f"explanation provider unavailable: {job2_why}",
                spoken=opener + " I can't explain further right now.",
            )
        else:
            vm.explanation = ExplanationVM(
                listing_id=lid, opener=opener, claims=claims, gaps=gaps, sources=sources
            )
            vm.snapshot = SnapshotVM(
                listing_id=lid, claims=claims, gaps=gaps, limited=not bundle.chunks
            )
            out = Answered(
                view_model=vm,
                spoken=" ".join([opener] + [c.text for c in claims] + gaps),
            )
        object.__setattr__(out, "_already_spoken", True)  # lane B spoke as it went
        return out

    async def _lane_a(self, session: Session, text: str) -> TurnOutcome:
        try:
            res: Job1Result = await self.job1.extract(text, session.constraints)
        except Job1Down:
            return Failed(
                capability="understanding",
                tell_renter="I didn't catch that — one moment, please say it again.",
                retry_worth_it=True,
                spoken="I didn't catch that. Could you say it again?",
            )

        if res.intent == "out_of_scope":
            return self._say(session, CONVERSATIONAL_REPLIES["out_of_scope"])
        if res.intent == "owner_contact":
            return self._say(session, CONVERSATIONAL_REPLIES["owner_contact"])

        # Spec §6.25: Job 1 marks a sentence in another language, or mixed with one, "unclear".
        # Nothing in it is acted on. A locality that came through recognisably is named back
        # for a yes before it is used; anything else heard - a budget, a bedroom count - is
        # dropped, never guessed. This is a statement of scope, not a clarifying question, so
        # it does not spend the §6.29 budget.
        if res.intent == "unclear":
            places = [e for e in res.edits if e.field == "localities" and e.op in ("add", "set")]
            if places:
                session.pending = ConfirmLocality(edits=places)
                names = " and ".join(str(e.value) for e in places)
                q = CONVERSATIONAL_REPLIES["english_only_locality"].format(localities=names)
                return NeedsInput(question=q, field="locality", options=["yes", "no"], spoken=q)
            q = CONVERSATIONAL_REPLIES["english_only"]
            return NeedsInput(question=q, field="english", spoken=q)

        booked = await self.booking_flow.handle(session, res, text)
        if booked is not None:
            return booked

        if res.reference is not None:
            return self._resolve_reference(session, res.reference)

        # Clarifying questions — ambiguities from Job 1 (spec §6.26, §6.24, §6.6)
        if res.ambiguities:
            if session.clarifying_asked < self.settings.max_clarifying_questions:
                session.clarifying_asked += 1
                a = res.ambiguities[0]
                return NeedsInput(question=a.question, field=a.field, spoken=a.question)
            # Budget exhausted: proceed on what was confirmed, and say so (spec §6.29)
            return await self._shortlist_turn(
                session, provisional=True, unknown_fields=[a.field for a in res.ambiguities]
            )

        if isinstance(session.pending, ConfirmHeard):
            heard = session.pending.text
            session.pending = None
            if res.intent == "confirm_yes":
                # Replay the confirmed words as an ordinary turn, re-entering the LANE
                # rather than `handle_text`. `_dispatch` is already holding `session.lock`
                # and `asyncio.Lock` is not re-entrant, so recursing through `handle_text`
                # deadlocks the turn forever - which is exactly what it did until a test
                # sat on it for 560 s. Re-classifying keeps a replayed "why ...?" on lane B.
                if classify_turn(heard, has_shortlist=not session.shortlist.is_empty()) == "B":
                    return await self._lane_b(session, heard)
                return await self._lane_a(session, heard)
            if res.intent == "confirm_no":
                q = CONVERSATIONAL_REPLIES["heard_wrong"]
                return NeedsInput(question=q, field="heard", spoken=q)
            # Anything else is the renter simply saying it again: fall through and treat
            # this turn as the real one rather than asking a second time.

        if isinstance(session.pending, ConfirmLocality):
            confirmed = session.pending
            session.pending = None
            if res.intent == "confirm_yes":
                applied = apply_edits(session.constraints, confirmed.edits)
                if isinstance(applied, Contradiction):
                    session.clarifying_asked += 1
                    return NeedsInput(
                        question=applied.question, field=applied.field, spoken=applied.question
                    )
                session.constraints = applied
                # Fall through: the §2.1 readback (first shortlist) or a refined shortlist.
            elif res.intent == "confirm_no":
                q = CONVERSATIONAL_REPLIES["locality_in_english"]
                return NeedsInput(question=q, field="locality", spoken=q)
            # Anything else is the renter saying it again, in English: this turn is the real one.

        if res.intent == "confirm_yes" and isinstance(session.pending, ConfirmConstraints):
            session.constraints = confirm_all(session.constraints)
            session.pending = None
            return await self._shortlist_turn(session)

        if res.intent == "confirm_no" and isinstance(session.pending, ConfirmConstraints):
            session.pending = None
            q = CONVERSATIONAL_REPLIES["what_should_i_change"]
            return NeedsInput(question=q, field="constraints", spoken=q)

        if res.edits:
            resolved: list[ConstraintEdit] = []
            for e in res.edits:
                if e.field == "commute" and e.op == "set":
                    point = self.store.place(str(e.value))  # build-time table, no geocoding (A3)
                    if point is None:
                        session.clarifying_asked += 1
                        known = ", ".join(self.store.place_names()[:6])
                        q = f"Where do you commute to? I know {known}."
                        return NeedsInput(question=q, field="commute", spoken=q)
                    e = ConstraintEdit("commute", "set", point)
                resolved.append(e)
            res.edits = resolved
            applied = apply_edits(session.constraints, res.edits)
            if isinstance(applied, Contradiction):
                session.clarifying_asked += 1
                return NeedsInput(
                    question=applied.question, field=applied.field, spoken=applied.question
                )
            session.constraints = applied

        if session.constraints.is_empty():
            q = CONVERSATIONAL_REPLIES["no_constraints"]
            return NeedsInput(
                question=q, field="constraints", spoken="Tell me a budget and a locality to start."
            )

        if session.shortlist.is_empty():
            # First shortlist: read everything back and wait for a yes (spec §2.1)
            session.pending = ConfirmConstraints()
            rb = "; ".join(session.constraints.readback())
            q = CONVERSATIONAL_REPLIES["readback"].format(readback=rb)
            return NeedsInput(
                question=q, field="constraints_readback", options=["yes", "no"], spoken=q
            )

        # Refinement on an existing shortlist: apply immediately, preserving order (spec §2.2)
        return await self._shortlist_turn(session)

    # ---- helpers

    def _say(self, session: Session, sentence: str) -> Answered:
        return Answered(view_model=self._view(session, notices=[sentence]), spoken=sentence)

    def _view(self, session: Session, notices: list[str] | None = None) -> AnsweredViewModel:
        sl = (
            self.vm.shortlist(session.shortlist, session.constraints.commute)
            if not session.shortlist.is_empty()
            else None
        )
        return AnsweredViewModel(
            constraints_readback=session.constraints.readback(),
            shortlist=sl,
            notices=notices or [],
        )

    def _resolve_reference(self, session: Session, n: int) -> TurnOutcome:
        heard = session.last_read_order
        if not heard or n < 1 or n > len(heard):
            return NeedsInput(
                question=CONVERSATIONAL_REPLIES["which_listing"],
                field="reference",
                spoken="Which one do you mean?",
            )
        lid = heard[n - 1]
        card = self.vm.card(lid, n, session.constraints.commute)
        session.focus_listing_id = lid
        if heard != session.shortlist.order:  # the list changed since they heard it (§6.30)
            q = f"Do you mean the {card.bhk_type} in {card.locality} at {card.rent}?"
            return NeedsInput(question=q, field="reference", options=["yes", "no"], spoken=q)
        return self._say(
            session,
            f"Okay — the {card.bhk_type} in {card.locality} at {card.rent}. "
            "Ask me why, or say 'book it'.",
        )

    async def _shortlist_turn(
        self,
        session: Session,
        provisional: bool = False,
        unknown_fields: list[str] | None = None,
    ) -> TurnOutcome:
        listings = list(self.store.listings.values())
        previous = session.shortlist
        with telemetry.span("shortlist.engine"):
            if previous.is_empty():
                new = engine.build(listings, session.constraints, self.availability.is_available)
            else:
                new = engine.refine(
                    previous, listings, session.constraints, self.availability.is_available
                )

        notices: list[str] = []
        removed = [
            x.listing_id
            for x in new.excluded
            if x.field == "availability" and x.listing_id in previous.order
        ]
        if removed:
            n = len(removed)
            notices.append(
                f"{n} listing{'s' if n > 1 else ''} in your shortlist "
                f"{'are' if n > 1 else 'is'} no longer available and "
                f"{'have' if n > 1 else 'has'} been removed."
            )
        if provisional:
            notices.append(
                CONVERSATIONAL_REPLIES["provisional_notice"] + ", ".join(unknown_fields or [])
            )

        session.shortlist = new

        if new.is_empty():
            if removed and not previous.is_empty():  # every listing went (spec §6.39)
                session.shortlist = Shortlist()
                msg = CONVERSATIONAL_REPLIES["all_withdrawn"]
                return Empty(unmet=[], suggestions=[], spoken=msg)
            unmet = engine.binding_constraints(new, session.constraints)
            tips = engine.suggest_relaxations(new, session.constraints, self.store.localities)
            binding = unmet[0] if unmet else None
            where = (
                " in " + " or ".join(session.constraints.localities)
                if session.constraints.localities
                else ""
            )
            if binding and binding.field == "rent_max":
                what = f"nothing under {rupees(session.constraints.rent_max)}"
            elif binding:
                what = f"nothing matching your {binding.field.replace('_', ' ')}"
            else:
                what = "nothing"
            spoken = f"I found {what}{where}"
            if tips:
                spoken += " — " + ", ".join(tips)
            spoken += ". I won't relax anything myself; tell me what to change."
            session.last_read_order = []
            return Empty(unmet=unmet, suggestions=tips, spoken=spoken)

        session.last_read_order = new.order
        vm = self._view(session, notices=notices)
        first = self.vm.card(new.order[0], 1, session.constraints.commute)
        n = len(new.order)
        spoken = (
            f"I found {n} listing{'s' if n > 1 else ''}. First is a {first.bhk_type} in "
            f"{first.locality} at {first.rent}, {first.transit.spoken}."
        )
        for u in vm.shortlist.unknown_on:
            spoken += " " + u.spoken
        if notices:
            spoken = " ".join(notices) + " " + spoken
        return Answered(view_model=vm, spoken=spoken.strip())
