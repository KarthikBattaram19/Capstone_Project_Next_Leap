"""The only part that knows the whole turn (arch §6.1). Lane A answers, lane B explains."""

from __future__ import annotations

import asyncio
import difflib
import re
import sys
from collections.abc import Callable

from scout.config import Settings
from scout.contract.outcome import Answered, Degraded, Empty, Failed, NeedsInput, TurnOutcome
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation.booking_flow import BookingFlow, BookingNotWired
from scout.conversation.job1 import Job1, Job1Down, Job1Result
from scout.conversation.router import (
    classify_turn,
    mentions_requirement,
    normalise_ordinals,
    parse_ordinal,
)
from scout.conversation.session import (
    AwaitArea,
    AwaitCode,
    AwaitLocalityChoice,
    ConfirmConstraints,
    ConfirmHeard,
    ConfirmLocality,
    Session,
)
from scout.conversation.speaker import Speaker, split_sentences
from scout.conversation.voice_booking import spoken_code
from scout.domain.constraints import ConstraintEdit, ConstraintSet
from scout.domain.listing import Parking
from scout.domain.locality_names import one_per_place, squash, variant_key
from scout.domain.money import rupees
from scout.domain.osm import OsmQuery
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
    # A1: English that Job 1 could not turn into anything. Not a statement of scope - the
    # renter spoke English, and telling them to was the bug (production, 2026-09-17).
    "unclear": (
        "Sorry, I didn't follow that. Could you say it another way — for example, "
        "'a 2BHK in Koramangala under 35,000'?"
    ),
    # A4, persona P-5: a complaint about her answers is taken, then the task is offered again.
    "feedback": (
        "Sorry about that — I'll keep my answers short and to the point. I can find flats "
        "to rent in Bengaluru, tell you about a listing, and book a visit. What would you "
        "like next?"
    ),
    # A5: a close, never a cancel. Nothing booked is touched.
    "goodbye": "Thank you for talking with me — goodbye, and good luck with the flat hunt.",
    "locality_in_english": "Okay. Which locality would you like? Please say it in English.",
    # B1: a bare yes or no to "Did you mean A, B or C?" names none of them.
    "which_of_these": "Which one do you mean — {names}?",
    # B1: code-like words that do not make a six-character code.
    "code_again": "Please say the six characters one at a time.",
    # E2: requirements the dataset cannot answer, said instead of emptying the shortlist.
    "lift_not_stated": "The listings don't say whether there's a lift, so I can't search on that.",
    "parking_kind_not_stated": (
        "The listings say only whether there's parking, not whether it's for a car or a bike, "
        "so I'll look for any parking."
    ),
    # B3: the last locality was removed, or none of the names offered was the one.
    "which_locality": "Which locality would you like instead?",
    # F1: no place and no commute point. One question before the first shortlist.
    "which_area": "Bengaluru is big — is there an area you prefer, or somewhere you commute to?",
    # F1: the listings carry no rating, and rent is a generated placeholder
    # (data/SOURCE_NOTES.md), so "better" is answered with the order they are in and the
    # orders the data supports.
    "better_listings": (
        "The listings carry no rating or review, so I can't rank one as better. They're in "
        "order {order}. I can put them {offers} instead."
    ),
    "no_commute_point": (
        "I don't know where you commute to yet. Tell me, and I can put the nearest first."
    ),
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


# Intents that are answered before any requirement is read: nothing to note about them.
_NO_EDITS_INTENTS = frozenset(
    {"out_of_scope", "owner_contact", "feedback", "goodbye", "unclear", "other_language"}
)


def _with_notes(out: TurnOutcome, notes: list[str]) -> TurnOutcome:
    """The outcome with notes said first: a requirement that could not be searched as asked."""
    if not notes or isinstance(out, Failed):
        return out
    said = " ".join(notes)
    update: dict = {"spoken": f"{said} {out.spoken}"}
    if isinstance(out, NeedsInput):
        update["question"] = f"{said} {out.question}"
    if isinstance(out, (Answered, Degraded)):
        vm = out.view_model
        update["view_model"] = vm.model_copy(update={"notices": [*notes, *vm.notices]})
    return out.model_copy(update=update)


# F1: "anywhere" in any sentence settles where to search; the looser answers count only as
# an answer to "is there an area you prefer?".
_ANYWHERE = re.compile(
    r"\banywhere\b|\b(?:whole|entire)\s+(?:of\s+)?(?:the\s+)?(?:city|bengaluru|bangalore)\b|"
    r"\ball\s+(?:over|across)\s+(?:the\s+city|bengaluru|bangalore)\b|"
    r"\bany\s+(?:area|locality|location)\b",
    re.IGNORECASE,
)
_NO_AREA = re.compile(
    r"^\W*(?:no|nope|not really|no preference|(?:it\s+)?does(?:n'?t| not) matter|any|"
    r"whatever|you (?:choose|decide|pick)|(?:it'?s\s+)?up to you|i leave it to you|"
    r"no particular (?:area|place|preference))(?:\s+(?:is fine|works|is ok(?:ay)?))?\W*$",
    re.IGNORECASE,
)
# F1: asking for another order, or asking why these and not better ones.
_ORDER_WORDS = {
    "largest": re.compile(
        r"\b(?:largest|biggest|larger|bigger)(?:\s+(?:ones?|flats?|listings?))?\s+first\b|"
        r"\bsort(?:ed)?\s+(?:them\s+)?by\s+(?:size|area|square\s+f\w+)\b",
        re.IGNORECASE,
    ),
    "metro": re.compile(
        r"\b(?:nearest|closest)\s+(?:to\s+)?(?:the\s+|a\s+)?metro(?:\s+station)?\s+first\b|"
        r"\bsort(?:ed)?\s+(?:them\s+)?by\s+(?:the\s+)?metro\b",
        re.IGNORECASE,
    ),
    "commute": re.compile(
        r"\b(?:nearest|closest)\s+to\s+(?:my\s+|the\s+)?(?:work|office|workplace|commute)"
        r"\s+first\b|\bsort(?:ed)?\s+(?:them\s+)?by\s+(?:my\s+)?commute\b",
        re.IGNORECASE,
    ),
    "cheapest": re.compile(
        r"\bcheapest\s+first\b|\bsort(?:ed)?\s+(?:them\s+)?by\s+(?:rent|price)\b",
        re.IGNORECASE,
    ),
}
_BETTER = re.compile(
    r"\b(?:better|best)\s+(?:listings?|options?|flats?|ones?|propert(?:y|ies)|places?|homes?|"
    r"houses?|apartments?|choices?|locations?|matches)\b|\b(?:anything|something)\s+better\b|"
    r"\bin what order\b|"
    r"\bhow (?:are|did you) (?:they|these|them|you)\s+(?:sorted|ordered|sort|order)\b",
    re.IGNORECASE,
)
_ORDER_SAID = {
    "cheapest": "of rent, cheapest first, with a deposit of up to three months' rent ranked ahead",
    "largest": "of size, largest first",
    "metro": "of distance to the metro, nearest first",
    "commute": "of distance to where you commute, nearest first",
}
_ORDER_OFFER = {
    "cheapest": "cheapest first",
    "largest": "largest first",
    "metro": "nearest the metro first",
    "commute": "nearest to where you commute first",
}
_ORDER_BUTTON = {
    "cheapest": "cheapest first",
    "largest": "largest first",
    "metro": "nearest metro first",
    "commute": "nearest to work first",
}


def _wanted(c: ConstraintSet) -> str:
    """What was not found, in plain words: "3BHK under ₹70,000 in Indiranagar"."""
    noun = [_plain(c.furnishing), _plain(c.bhk_type), _plain(c.property_type)]
    words = [w for w in noun if w] or ["listings"]
    if c.rent_min is not None and c.rent_max is not None:
        words.append(f"between {rupees(c.rent_min)} and {rupees(c.rent_max)}")
    elif c.rent_max is not None:
        words.append(f"under {rupees(c.rent_max)}")
    elif c.rent_min is not None:
        words.append(f"from {rupees(c.rent_min)}")
    if c.deposit_max is not None:
        words.append(f"with a deposit up to {rupees(c.deposit_max)}")
    if c.parking_required:
        words.append("with parking")
    if c.lift_required:
        words.append("with a lift")
    if c.amenities_required:
        words.append("with " + " and ".join(sorted(c.amenities_required)))
    if c.square_footage_min:
        words.append(f"of at least {c.square_footage_min} sq ft")
    if c.available_by:
        words.append(f"available by {c.available_by.isoformat()}")
    if c.localities:
        words.append("in " + " or ".join(one_per_place(c.localities)))
    return " ".join(words)


_BARE_YES = re.compile(
    r"^\W*(?:yes|yeah|yep|yup|ya|sure|ok(?:ay)?|correct|right|that'?s right|haan)\W*$",
    re.IGNORECASE,
)
_BARE_NO = re.compile(r"^\W*(?:no|nope|nah|not that)\W*$", re.IGNORECASE)
_NONE_OF_THEM = re.compile(
    r"^\W*(?:no\W*)?(?:neither|none)(?: of (?:them|those|these))?\W*$", re.IGNORECASE
)
_NOT = re.compile(r"\bnot\b|n't\b", re.IGNORECASE)
_BOTH = re.compile(r"\b(?:both|all of them|all three|any of them)\b", re.IGNORECASE)
_BARE_ORDINAL = {"first": 1, "second": 2, "third": 3, "last": -1}
_BARE_ORDINAL |= {f"the {k}": v for k, v in _BARE_ORDINAL.items()}


def _result(intent: str, **fields) -> Job1Result:
    """What Job 1 would have returned, built in code for an answer read before Job 1 (B1)."""
    base = {"edits": [], "ambiguities": [], "reference": None, "email": None, "code": None}
    base["slot_choice"] = None
    return Job1Result(intent=intent, **(base | fields))


def _plain(v: object) -> str:
    return str(getattr(v, "value", v)).replace("_", " ") if v else ""


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
        text = normalise_ordinals(text)
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
            ordered = self._order_turn(session, text)
            if ordered is not None:
                outcome = ordered
            elif turn_type == "B":
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
        from scout.grounding.assembler import ClaimAssembler, worth_saying
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
        # In a worker thread: retrieval embeds the question on the CPU, and on the event
        # loop it froze every session's audio for its duration (2.7 s on production,
        # 2026-09-17).
        bundle = await asyncio.to_thread(registry.resolve, lid, text, commute_point)
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
        # E1: a "why this one?" answer was a 57 s monologue on production (2026-09-17). She
        # hears the opener, at most three short claims (two when a gap line follows) and at
        # most one line about gaps; everything else is on screen.
        max_spoken = 2 if assembler.gap_summary(text) else 3
        spoken_claims: list[str] = []
        seen: set[str] = set()
        summary: str | None = None
        try:
            session.job2_task = asyncio.current_task()
            async for s in self.job2.explain(bundle, text):
                claim = assembler.bind(s)
                if claim is None:
                    continue  # dropped: no resolvable citation
                key = " ".join(claim.text.lower().split())
                if key in seen:
                    continue  # the same sentence twice is said and shown once
                seen.add(key)
                claims.append(ClaimVM(text=claim.text, citation_refs=claim.refs))
                bound_facts.update(claim.facts)
                if len(spoken_claims) < max_spoken and worth_saying(claim, lid):
                    spoken_claims.append(claim.text)
                    await queue.put(claim.text)  # released only once its citation resolved
            summary = assembler.gap_summary(text, getattr(self.job2, "last_gaps", []))
            if summary is not None and len(spoken_claims) < 3:
                await queue.put(summary)
            else:
                summary = None
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

        gaps = assembler.all_gaps(getattr(self.job2, "last_gaps", []))
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
                spoken=" ".join([opener, *spoken_claims, *([summary] if summary else [])]),
            )
        object.__setattr__(out, "_already_spoken", True)  # lane B spoke as it went
        return out

    async def _lane_a(self, session: Session, text: str) -> TurnOutcome:
        if _ANYWHERE.search(text):
            session.area_settled = True  # F1: "anywhere in Bengaluru" needs no area question
        # B1: an answer to a question she was just asked is read in code, before Job 1,
        # which is not told what was asked and read "The 2nd 1, T C" and "9VR7JP." cold.
        answered = self._answer_to_pending(session, text)
        if isinstance(answered, NeedsInput):
            return answered
        if answered is not None:
            res: Job1Result = answered
        else:
            try:
                res = await self.job1.extract(text, session.constraints)
            except Job1Down:
                return Failed(
                    capability="understanding",
                    tell_renter="I didn't catch that — one moment, please say it again.",
                    retry_worth_it=True,
                    spoken="I didn't catch that. Could you say it again?",
                )

        if res.intent in _NO_EDITS_INTENTS:
            return await self._act(session, res, text)
        notes = self._unsearchable(res)
        if (
            notes
            and not res.edits
            and res.intent in ("set_preferences", "refine")
            and session.pending is None
            and not session.shortlist.is_empty()
        ):
            return self._say(session, " ".join(notes))  # "only ones with a lift": nothing to redo
        parking_before = session.constraints.parking_required
        out = await self._act(session, res, text)
        kind = session.constraints.parking_required
        if (
            isinstance(kind, Parking)
            and kind != parking_before
            and not session.parking_kind_explained
            and self._nobody_states("parking")
        ):
            session.parking_kind_explained = True
            notes.append(CONVERSATIONAL_REPLIES["parking_kind_not_stated"])
        return _with_notes(out, notes)

    async def _act(self, session: Session, res: Job1Result, text: str) -> TurnOutcome:
        """Lane A once the words are understood: Job 1's result, or the answer read in code."""
        if res.intent == "out_of_scope":
            return self._say(session, CONVERSATIONAL_REPLIES["out_of_scope"])
        if res.intent == "owner_contact":
            return self._say(session, CONVERSATIONAL_REPLIES["owner_contact"])
        if res.intent == "feedback":
            return self._say(session, CONVERSATIONAL_REPLIES["feedback"])
        if res.intent == "goodbye":
            return self._say(session, CONVERSATIONAL_REPLIES["goodbye"])
        if res.intent == "unclear":
            return self._not_followed()

        # Spec §6.25: Job 1 marks a sentence in another language, or mixed with one,
        # "other_language".
        # Nothing in it is acted on. A locality that came through recognisably is named back
        # for a yes before it is used; anything else heard - a budget, a bedroom count - is
        # dropped, never guessed. This is a statement of scope, not a clarifying question, so
        # it does not spend the §6.29 budget.
        if res.intent == "other_language":
            places = [e for e in res.edits if e.field == "localities" and e.op in ("add", "set")]
            if places:
                session.pending = ConfirmLocality(edits=places)
                names = " and ".join(one_per_place(str(e.value) for e in places))
                q = CONVERSATIONAL_REPLIES["english_only_locality"].format(localities=names)
                return NeedsInput(question=q, field="locality", options=["yes", "no"], spoken=q)
            q = CONVERSATIONAL_REPLIES["english_only"]
            return NeedsInput(question=q, field="english", spoken=q)

        booked = await self.booking_flow.handle(session, res, text)
        if booked is not None:
            return booked
        if res.intent == "cancel":
            # The booking flow declined it: no cancel word with a visit word, and no code (A5).
            return self._not_followed()

        if res.reference is not None:
            return self._resolve_reference(session, res.reference)

        # Clarifying questions — ambiguities from Job 1 (spec §6.26, §6.24, §6.6)
        if res.ambiguities:
            # What the sentence said clearly is kept while the rest is asked about. Production,
            # 2026-09-17: "2 BHK in Khyakpuram" asked which locality and dropped the 2 BHK.
            # Job 1 has already left the unclear field out of `edits`. If the clear part would
            # itself need a question, it waits: a second question would bury the first.
            if res.edits:
                applied = self._applied(session, res.edits)
                if not isinstance(applied, NeedsInput):
                    session.constraints = applied
            if session.clarifying_asked < self.settings.max_clarifying_questions:
                session.clarifying_asked += 1
                a = res.ambiguities[0]
                if a.field == "locality" and a.options:
                    session.pending = AwaitLocalityChoice(options=list(a.options), heard=a.heard)
                return NeedsInput(
                    question=a.question, field=a.field, options=a.options, spoken=a.question
                )
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
            if not res.edits:
                q = CONVERSATIONAL_REPLIES["what_should_i_change"]
                return NeedsInput(question=q, field="constraints", spoken=q)
            # B2: "No. I mentioned Koramangala." carries its own correction: apply it and
            # read back again below, rather than asking what to change.

        if res.edits:
            applied = self._applied(session, res.edits)
            if isinstance(applied, NeedsInput):
                session.clarifying_asked += 1
                return applied
            lost_place = (
                bool(session.constraints.localities)
                and not applied.localities
                and any(e.field == "localities" and e.op == "remove" for e in res.edits)
            )
            session.constraints = applied
            # B3: taking away the only locality is not a request to search the whole city.
            if lost_place and session.clarifying_asked < self.settings.max_clarifying_questions:
                session.clarifying_asked += 1
                session.pending = None
                session.area_settled = True  # the place was just asked about (F1)
                return self._which_locality()

        if session.constraints.is_empty():
            q = CONVERSATIONAL_REPLIES["no_constraints"]
            return NeedsInput(
                question=q, field="constraints", spoken="Tell me a budget and a locality to start."
            )

        if session.shortlist.is_empty():
            c = session.constraints
            whole_city = not c.localities and c.commute is None
            # F1: "I leave it to you to give me the best location" searched 431 localities
            # (production, 2026-09-17). With no place and no commute point, ask once.
            if (
                whole_city
                and not session.area_settled
                and session.clarifying_asked < self.settings.max_clarifying_questions
            ):
                session.area_settled = True
                session.clarifying_asked += 1
                session.pending = AwaitArea()
                q = CONVERSATIONAL_REPLIES["which_area"]
                return NeedsInput(question=q, field="locality", spoken=q)
            # First shortlist: read everything back and wait for a yes (spec §2.1)
            session.pending = ConfirmConstraints()
            return self._readback(session)

        # Refinement on an existing shortlist: apply immediately, preserving order (spec §2.2)
        return await self._shortlist_turn(session)

    # ---- helpers

    def _order_turn(self, session: Session, text: str) -> TurnOutcome | None:
        """F1: "largest first" re-orders the shortlist; "any better listings?" says how it is
        ordered and what else it can be ordered by. Read in code, before either lane: "nearest
        metro first" would otherwise be explained, and "better" is not a requirement."""
        readback = session.shortlist.is_empty() and isinstance(session.pending, ConfirmConstraints)
        if not readback and (session.shortlist.is_empty() or session.pending is not None):
            return None
        if re.search(r"\d", text) or mentions_requirement(text) or self._names_place(text):
            return None  # "better ones under 30,000 in HSR" is a search
        if readback:
            # Production replay (2026-09-17): "Are there not any better listings?" while the
            # readback waited for a yes got "Sorry, I didn't follow that." The order is said
            # and the readback asked again; it stays pending, so "yes" still searches.
            if not _BETTER.search(text):
                return None
            said, _ = self._better_listings(session)
            again = self._readback(session)
            q = f"{said} {again.question}"
            return again.model_copy(update={"question": q, "spoken": q})
        asked = next((k for k, rx in _ORDER_WORDS.items() if rx.search(text)), None)
        if asked is not None:
            return self._reordered(session, asked)
        if not _BETTER.search(text):
            return None
        q, others = self._better_listings(session)
        return NeedsInput(
            question=q, field="order", options=[_ORDER_BUTTON[k] for k in others], spoken=q
        )

    @staticmethod
    def _better_listings(session: Session) -> tuple[str, list[str]]:
        """F1: why none is "better", the order the shortlist is in, and the other orders."""
        kinds = ["cheapest", "largest", "metro"] + (
            ["commute"] if session.constraints.commute else []
        )
        others = [k for k in kinds if k != session.order_by]
        offers = [_ORDER_OFFER[k] for k in others]
        said = ", ".join(offers[:-1]) + f" or {offers[-1]}"
        q = CONVERSATIONAL_REPLIES["better_listings"].format(
            order=_ORDER_SAID[session.order_by], offers=said
        )
        return q, others

    @staticmethod
    def _readback(session: Session) -> NeedsInput:
        """The §2.1 readback before the first shortlist, waiting for a yes."""
        c = session.constraints
        whole_city = not c.localities and c.commute is None
        parts = c.readback() + (["anywhere in Bengaluru"] if whole_city else [])
        q = CONVERSATIONAL_REPLIES["readback"].format(readback="; ".join(parts))
        return NeedsInput(question=q, field="constraints_readback", options=["yes", "no"], spoken=q)

    def _names_place(self, text: str) -> bool:
        said = squash(text)
        return any(len(k) >= 4 and k in said for k in map(squash, self.store.localities))

    def _reordered(self, session: Session, kind: str) -> TurnOutcome:
        point = session.constraints.commute
        if kind == "commute" and point is None:
            q = CONVERSATIONAL_REPLIES["no_commute_point"]
            return NeedsInput(question=q, field="commute", spoken=q)
        listings = self.store.listings

        def size(i: str):
            sqft = listings[i].field("square_footage").value
            return -sqft if sqft is not None else None

        def metro(i: str):
            return self.store.osm(i, OsmQuery.NEAREST_METRO).distance_m

        def commute(i: str):
            d = self.commute.to_point(i, point).value
            return d.metres if d is not None else None

        if kind == "cheapest":
            ranked = engine.build(
                list(listings.values()), session.constraints, self.availability.is_available
            ).order
            rank = {i: n for n, i in enumerate(ranked)}
            key = rank.get
        else:
            key = {"largest": size, "metro": metro, "commute": commute}[kind]
        session.shortlist = engine.reorder(session.shortlist, key)
        session.order_by = kind
        order = session.shortlist.order
        session.last_read_order = order
        vm = self._view(session)
        first = self.vm.card(order[0], 1, point)
        spoken = (
            f"Here they are, {_ORDER_OFFER[kind]}. First is a {first.bhk_type} in "
            f"{first.locality} at {first.rent}, {first.transit.spoken}."
        )
        return Answered(view_model=vm, spoken=spoken)

    def _nobody_states(self, name: str) -> bool:
        return all(x.field(name).value is None for x in self.store.listings.values())

    def _unsearchable(self, res: Job1Result) -> list[str]:
        """Take out a requirement no listing can answer, and say so (E2). No listing in the
        dataset states a lift, so searching on one could only ever empty the shortlist."""
        lift = [e for e in res.edits if e.field == "lift_required" and e.op in ("set", "add")]
        if not lift or not self._nobody_states("lift"):
            return []
        res.edits = [e for e in res.edits if e not in lift]
        return [CONVERSATIONAL_REPLIES["lift_not_stated"]]

    def _applied(self, session: Session, edits: list[ConstraintEdit]):
        """The constraints with `edits` applied, or the question that has to come first."""
        resolved: list[ConstraintEdit] = []
        for e in edits:
            if e.field == "commute" and e.op == "set":
                point = self.store.place(str(e.value))  # build-time table, no geocoding (A3)
                if point is None:
                    known = ", ".join(self.store.place_names()[:6])
                    q = f"Where do you commute to? I know {known}."
                    return NeedsInput(question=q, field="commute", spoken=q)
                e = ConstraintEdit("commute", "set", point)
            resolved.append(e)
        applied = apply_edits(session.constraints, resolved)
        if isinstance(applied, Contradiction):
            return NeedsInput(
                question=applied.question, field=applied.field, spoken=applied.question
            )
        return applied

    def _answer_to_pending(self, session: Session, text: str) -> Job1Result | NeedsInput | None:
        """What the words alone answer to the question pending, standing in for Job 1's
        result; a question to ask again; or None to run Job 1 as usual."""
        p = session.pending
        if isinstance(p, AwaitArea):
            session.pending = None
            if _NO_AREA.match(text) or _ANYWHERE.search(text):
                session.area_settled = True
                if not re.search(r"\d", text) and len(text.split()) <= 8:
                    return _result("set_preferences")  # the whole city, nothing else said
            return None  # a place, a commute point or more: Job 1 reads it
        if isinstance(p, AwaitLocalityChoice):
            return self._locality_choice(session, p, text)
        if isinstance(p, AwaitCode):
            place_words = {w.upper() for loc in self.store.localities for w in loc.split()}
            code = spoken_code(text, place_words)
            if len(code) == 6:
                session.pending = None
                return _result(p.action, code=code)
            if len(code) >= 3:
                q = CONVERSATIONAL_REPLIES["code_again"]
                return NeedsInput(question=q, field="code", spoken=q)
            session.pending = None  # not an answer: an ordinary sentence
            return None
        names_slot = getattr(self.booking_flow, "names_offered_slot", None)
        if names_slot is not None and names_slot(session, text):
            return _result("set_preferences")  # the booking flow reads the time from the words
        return None

    def _locality_choice(
        self, session: Session, p: AwaitLocalityChoice, text: str
    ) -> Job1Result | NeedsInput | None:
        """The names offered that the words pick: by name (spaces and dots ignored, or a
        close spelling), "both", "the second one", or a bare yes to a single name."""
        options = p.options
        said = squash(text)
        if _NOT.search(text):  # "not TC Palya" names a place to leave out: Job 1 reads it
            session.pending = None
            return None
        chosen = [o for o in options if squash(o) and squash(o) in said]
        if not chosen:
            words = re.findall(r"[a-z0-9]+", text.lower())
            windows = {"".join(words[i : i + k]) for k in (1, 2, 3) for i in range(len(words))}
            by_squash = {squash(o): o for o in options}
            close = {
                by_squash[m]
                for w in windows
                if len(w) >= 3
                for m in difflib.get_close_matches(w, by_squash, 1, 0.8)
            }
            chosen = [o for o in options if o in close]
        if not chosen and _BOTH.search(text):
            chosen = list(options)
        if not chosen:
            n = parse_ordinal(text) or _BARE_ORDINAL.get(text.strip(" .!?,").lower())
            if n == -1:
                n = len(options)
            if n is not None and 1 <= n <= len(options):
                chosen = [options[n - 1]]
        if not chosen and _BARE_YES.match(text) and len(options) == 1:
            chosen = list(options)
        if chosen:
            session.pending = None
            residue = said
            for o in chosen:
                residue = residue.replace(squash(o), "")
            if re.search(r"\d", residue) or len(text.split()) > 8:
                return None  # more than a choice ("Koramangala, under 40,000"): Job 1 reads it
            covered = self.store.localities
            names = [  # C1: every spelling of the place chosen
                loc
                for o in chosen
                for loc in ([n for n in covered if variant_key(n) == variant_key(o)] or [o])
            ]
            edits = [ConstraintEdit("localities", "add", n) for n in dict.fromkeys(names)]
            return _result("set_preferences", edits=edits)
        if len(options) > 1 and (_BARE_YES.match(text) or _BARE_NO.match(text)):
            names = ", ".join(options[:-1]) + f" or {options[-1]}"
            q = CONVERSATIONAL_REPLIES["which_of_these"].format(names=names)
            return NeedsInput(question=q, field="locality", options=list(options), spoken=q)
        session.pending = None
        if _BARE_NO.match(text) or _NONE_OF_THEM.match(text):
            return self._which_locality()
        return None

    @staticmethod
    def _which_locality() -> NeedsInput:
        q = CONVERSATIONAL_REPLIES["which_locality"]
        return NeedsInput(question=q, field="locality", spoken=q)

    @staticmethod
    def _not_followed() -> NeedsInput:
        """English that could not be read (A1). Not a clarifying question about a field, so it
        does not spend the §6.29 budget."""
        q = CONVERSATIONAL_REPLIES["unclear"]
        return NeedsInput(question=q, field="unclear", spoken=q)

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
            c = session.constraints
            available = self.availability.is_available
            unmet = engine.binding_constraints(new, c)
            # The place binds only when the rest of what she asked for exists elsewhere;
            # then the neighbours offered are ones that have it. Production, 2026-09-17:
            # "nothing matching your localities" was said whatever ruled everything out,
            # because every listing elsewhere counts as excluded by the locality.
            nearby: list[str] = []
            if c.localities:
                elsewhere = engine.build(listings, engine.without(c, "localities"), available)
                if elsewhere.order:
                    having = sorted({self.store.listings[i].locality for i in elsewhere.order})
                    nearby = engine.nearest_localities(c.localities, self.store.places, having)
            not_stated = {}
            for fld, ids in new.unknown.items():
                shown = engine.build(listings, engine.without(c, fld), available).order
                not_stated[fld] = len(set(shown) & set(ids))
            tips = engine.suggest_relaxations(new, c, nearby, not_stated)
            spoken = f"No {_wanted(c)}."
            if tips:
                spoken += " You could " + ", or ".join(tips) + "."
            spoken += " I won't relax anything myself; tell me what to change."
            session.last_read_order = []
            return Empty(unmet=unmet, suggestions=tips, spoken=spoken)

        session.last_read_order = new.order
        vm = self._view(session, notices=notices)
        first = self.vm.card(new.order[0], 1, session.constraints.commute)
        n = len(new.order)
        found = f"I found {n} listing{'s' if n > 1 else ''}"
        c = session.constraints
        if previous.is_empty():
            session.order_by = "cheapest"
            if not c.localities and c.commute is None:  # F1: say how the city is ordered
                found += " across Bengaluru, cheapest first"
        spoken = (
            f"{found}. First is a {first.bhk_type} in "
            f"{first.locality} at {first.rent}, {first.transit.spoken}."
        )
        for u in vm.shortlist.unknown_on:
            spoken += " " + u.spoken
        if notices:
            spoken = " ".join(notices) + " " + spoken
        return Answered(view_model=vm, spoken=spoken.strip())
