import pytest

from scout.config import Settings
from scout.contract.outcome import Answered, Empty, Failed, NeedsInput
from scout.conversation.job1 import Job1Down, Job1Result
from scout.conversation.orchestrator import NullSpeaker, TurnOrchestrator
from scout.conversation.session import ConfirmHeard, ConfirmLocality, SessionManager
from scout.domain.constraints import ConstraintEdit
from scout.engines.availability import AvailabilityRegister
from scout.platform.artefacts import ArtefactStore


class ScriptedJob1:
    def __init__(self, results):
        self.results = list(results)

    async def extract(self, text, current):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def j1(intent="set_preferences", edits=(), ambiguities=(), reference=None):
    return Job1Result(
        intent=intent,
        edits=list(edits),
        ambiguities=list(ambiguities),
        reference=reference,
        email=None,
        code=None,
        slot_choice=None,
    )


@pytest.fixture
def make(bundle_min):
    """A throwaway copy of the fixture bundle: opening the committed one dirties its sqlite."""

    def build(results):
        store = ArtefactStore.load(bundle_min)
        settings = Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_min
        )
        orch = TurnOrchestrator(
            store,
            settings,
            job1=ScriptedJob1(results),
            job2=None,
            availability=AvailabilityRegister(store),
            speaker_factory=lambda: NullSpeaker(),
        )
        return orch, SessionManager(60).create()

    return build


async def test_constraints_are_read_back_before_any_shortlist(make):
    orch, s = make(
        [
            j1(
                edits=[
                    ConstraintEdit("localities", "add", "Koramangala"),
                    ConstraintEdit("rent_max", "set", 40000),
                ]
            ),
            j1(intent="confirm_yes"),
        ]
    )
    o1 = await orch.handle_text(s, "2BHK in Koramangala under forty thousand")
    assert isinstance(o1, NeedsInput)
    assert "Koramangala" in o1.question and "40,000" in o1.question
    assert s.shortlist.is_empty()

    o2 = await orch.handle_text(s, "yes")
    assert isinstance(o2, Answered)
    assert o2.view_model.shortlist.order
    assert s.last_read_order == o2.view_model.shortlist.order


async def test_empty_is_a_result_and_names_the_binding_constraint(make):
    orch, s = make([j1(edits=[ConstraintEdit("rent_max", "set", 5000)]), j1(intent="confirm_yes")])
    # F1: "anywhere" settles where to search, so no area question comes first.
    await orch.handle_text(s, "anything under five thousand, anywhere")
    o = await orch.handle_text(s, "yes")
    assert isinstance(o, Empty)
    assert o.unmet[0].field == "rent_max"
    assert o.suggestions


async def test_job1_down_is_a_failed_error_not_an_empty_result(make):
    orch, s = make([Job1Down("429")])
    o = await orch.handle_text(s, "hello")
    assert isinstance(o, Failed) and o.capability == "understanding"


async def test_contradiction_asks_and_counts_against_the_budget(make):
    orch, s = make(
        [
            j1(
                edits=[
                    ConstraintEdit("localities", "add", "Koramangala"),
                    ConstraintEdit("rent_min", "set", 30000),
                ]
            ),
            j1(edits=[ConstraintEdit("rent_max", "set", 25000)]),
        ]
    )
    # A place, so F1's area question is not asked first and spent from the budget.
    await orch.handle_text(s, "only above 30k in Koramangala")
    o = await orch.handle_text(s, "under 25k")
    assert isinstance(o, NeedsInput)
    assert s.clarifying_asked == 1
    assert s.constraints.rent_max is None


async def test_budget_exhausted_proceeds_provisionally_and_says_so(make):
    from scout.conversation.job1 import Ambiguity

    amb = [Ambiguity(field="rent_max", heard="thirty five", question="Did you mean ₹35,000?")]
    # Six ambiguous turns: the first five ask, the sixth finds the budget spent and goes
    # ahead on what was confirmed, saying so (spec §6.29).
    orch, s = make([j1(ambiguities=amb)] * 6)
    s.constraints = s.constraints.with_(localities=("Koramangala",))
    for _ in range(5):
        await orch.handle_text(s, "budget thirty five")
    o = await orch.handle_text(s, "thirty five")
    assert s.clarifying_asked == 5
    assert isinstance(o, Answered)
    assert any("provisional" in n.lower() for n in o.view_model.notices)


async def test_refinement_keeps_untouched_cards_identical(make):
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]),
            j1(intent="confirm_yes"),
            j1(intent="refine", edits=[ConstraintEdit("rent_max", "set", 10**9)]),
        ]
    )
    await orch.handle_text(s, "Koramangala")
    before = (await orch.handle_text(s, "yes")).view_model.shortlist
    after = (await orch.handle_text(s, "under a crore")).view_model.shortlist
    assert before.order == after.order
    assert [c.model_dump_json() for g in before.groups for c in g.cards] == [
        c.model_dump_json() for g in after.groups for c in g.cards
    ]


async def test_unavailable_listing_is_removed_with_a_notice(make):
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]),
            j1(intent="confirm_yes"),
            j1(intent="refine", edits=[]),
        ]
    )
    await orch.handle_text(s, "Koramangala")
    o = await orch.handle_text(s, "yes")
    gone = o.view_model.shortlist.order[0]
    orch.availability.set(gone, False)
    o2 = await orch.handle_text(s, "show me again")
    assert gone not in o2.view_model.shortlist.order
    assert any("no longer available" in n for n in o2.view_model.notices)


# --- §6.25: another language is out of scope; a locality heard in it is confirmed first ---

HINDI_WITH_BUDGET = "mujhe Koramangala mein pachas hazaar tak chahiye"


def unclear_with(*edits):
    """Job 1's mark for a sentence in another language (spec §6.25)."""
    return j1(intent="other_language", edits=list(edits))


# --- A1, A4, A5 (voice fix batch 2026-09-17): English she did not follow, complaints, goodbye ---

ENGLISH_ONLY = "I can only help in English"


@pytest.mark.parametrize(
    "said",
    [
        "You are not acknowledging my request.",
        "You are giving irrelevant answers.",
        "I think you are not picking me correctly.",
        "Hello. Are you saying something? I did not listen from you.",
        "Hello",
        "I cannot listen to you.",
        "We were already discussing about a listing. Right?",
    ],
)
async def test_english_she_did_not_follow_is_not_told_to_speak_english(make, said):
    """Production 2026-09-17: eight English sentences got the English-only line, because
    Job 1's "unclear" meant both another language and did-not-understand."""
    orch, s = make([j1(intent="unclear")])

    o = await orch.handle_text(s, said)

    assert ENGLISH_ONLY not in o.spoken
    assert "Sorry, I didn't follow" in o.spoken
    assert "for example" in o.spoken.lower()
    assert s.pending is None and s.constraints.is_empty()
    assert s.clarifying_asked == 0


async def test_a_complaint_about_her_gets_an_apology_that_says_what_she_can_do(make):
    """A4: "Can you be more polite?" was answered with the out-of-scope line."""
    orch, s = make([j1(intent="feedback")])

    o = await orch.handle_text(s, "I think you are bit not so polite. Can you be more polite?")

    assert isinstance(o, Answered)
    assert "sorry" in o.spoken.lower()
    assert "not buying" not in o.spoken and ENGLISH_ONLY not in o.spoken
    assert "book a visit" in o.spoken
    assert s.shortlist.is_empty() and s.constraints.is_empty()


async def test_goodbye_is_a_polite_close_and_asks_for_nothing(make):
    """A5: "Okay. I'm ending the conversation here." asked for a confirmation code."""
    orch, s = make([j1(intent="goodbye")])

    o = await orch.handle_text(s, "Okay. I'm ending the conversation here.")

    assert isinstance(o, Answered)
    assert "code" not in o.spoken.lower() and "?" not in o.spoken
    assert "bye" in o.spoken.lower()


async def test_a_sentence_in_another_language_is_told_english_is_the_scope(make):
    orch, s = make([unclear_with()])

    o = await orch.handle_text(s, "kiraya kitna hai")

    assert isinstance(o, NeedsInput) and o.field == "english"
    assert "English" in o.question
    assert s.constraints.is_empty() and s.shortlist.is_empty()
    assert s.clarifying_asked == 0, "a statement of scope spent the clarifying-question budget"


async def test_a_locality_heard_in_another_language_is_confirmed_and_nothing_is_used_yet(make):
    orch, s = make(
        [
            unclear_with(
                ConstraintEdit("localities", "add", "Koramangala"),
                ConstraintEdit("rent_max", "set", 50000),
            )
        ]
    )

    o = await orch.handle_text(s, HINDI_WITH_BUDGET)

    assert isinstance(o, NeedsInput) and o.field == "locality"
    assert "Koramangala" in o.question and "English" in o.question
    assert o.options == ["yes", "no"]
    assert s.constraints.is_empty(), "the non-English sentence was acted on before a yes"
    assert isinstance(s.pending, ConfirmLocality)


async def test_yes_applies_only_the_locality_and_then_reads_everything_back(make):
    """A budget heard in another language is never used, even after the locality is confirmed."""
    orch, s = make(
        [
            unclear_with(
                ConstraintEdit("localities", "add", "Koramangala"),
                ConstraintEdit("rent_max", "set", 50000),
            ),
            j1(intent="confirm_yes"),
        ]
    )
    await orch.handle_text(s, HINDI_WITH_BUDGET)

    o = await orch.handle_text(s, "yes")

    assert s.constraints.localities == ("Koramangala",)
    assert s.constraints.rent_max is None, "a budget heard in another language was used"
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback"


async def test_no_uses_nothing_and_asks_for_the_locality_in_english(make):
    orch, s = make(
        [unclear_with(ConstraintEdit("localities", "add", "Koramangala")), j1(intent="confirm_no")]
    )
    await orch.handle_text(s, "nanage Koramangala alli mane beku")

    o = await orch.handle_text(s, "no")

    assert isinstance(o, NeedsInput) and o.field == "locality"
    assert "English" in o.question
    assert s.constraints.is_empty()
    assert s.pending is None


async def test_saying_it_again_in_english_is_taken_as_the_real_turn(make):
    orch, s = make(
        [
            unclear_with(ConstraintEdit("localities", "add", "Koramangala")),
            j1(
                edits=[
                    ConstraintEdit("localities", "add", "Koramangala"),
                    ConstraintEdit("rent_max", "set", 40000),
                ]
            ),
        ]
    )
    await orch.handle_text(s, "Koramangala mein chahiye")

    o = await orch.handle_text(s, "a 2BHK in Koramangala under forty thousand")

    assert s.constraints.localities == ("Koramangala",) and s.constraints.rent_max == 40000
    assert not isinstance(s.pending, ConfirmLocality)
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback"


# --- §6.20: a noisy transcript is confirmed, never guessed (Task 4.2 gap) ---


async def test_a_noisy_transcript_is_confirmed_before_it_ever_reaches_job1(make):
    """Spec §6.20. The check runs above Job 1 on purpose: a noisy utterance must not be
    guessed at, and on a 500-call day it should not cost a model call either."""
    orch, s = make([j1(edits=[ConstraintEdit("localities", "add", "Koramangala")])])

    o = await orch.handle_text(s, "two BHK in Koramangala", confidence=0.3)

    assert isinstance(o, NeedsInput)
    assert o.field == "heard"
    assert "two BHK in Koramangala" in o.question, "it must quote what was heard, not paraphrase"
    assert o.options == ["yes", "no"]
    assert len(orch.job1.results) == 1, "Job 1 was called on a transcript we did not trust"
    assert s.constraints.is_empty(), "a noisy transcript was applied before confirmation"


async def test_confirming_a_noisy_transcript_replays_the_original_words(make):
    """Saying yes must act on what was HEARD, not on the word "yes"."""
    orch, s = make(
        [j1(intent="confirm_yes"), j1(edits=[ConstraintEdit("localities", "add", "Koramangala")])]
    )
    await orch.handle_text(s, "two BHK in Koramangala", confidence=0.3)

    await orch.handle_text(s, "yes")

    assert s.constraints.localities == ("Koramangala",)
    assert s.pending is None or not isinstance(s.pending, ConfirmHeard)


async def test_rejecting_a_noisy_transcript_asks_for_it_again(make):
    orch, s = make([j1(intent="confirm_no")])
    await orch.handle_text(s, "mrrbl fnnn", confidence=0.2)

    o = await orch.handle_text(s, "no")

    assert isinstance(o, NeedsInput) and o.field == "heard"
    assert "again" in o.question
    assert not isinstance(s.pending, ConfirmHeard)


async def test_a_confident_transcript_is_never_confirmed_for_noise(make):
    """The check has to be a check. Confirming every turn would double the length of every
    conversation and make the readback meaningless."""
    orch, s = make(
        [j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]), j1(intent="confirm_yes")]
    )
    o = await orch.handle_text(s, "two BHK in Koramangala", confidence=0.95)
    assert not (isinstance(o, NeedsInput) and o.field == "heard")


async def test_a_noisy_answer_to_a_question_we_asked_is_not_re_confirmed(make):
    """A one-word "yes" scores low on its own. Re-confirming an answer we are already
    waiting on would loop the renter forever, so the check stands down while pending."""
    orch, s = make(
        [j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]), j1(intent="confirm_yes")]
    )
    await orch.handle_text(s, "Koramangala")
    assert s.pending is not None

    o = await orch.handle_text(s, "yes", confidence=0.2)

    assert isinstance(o, Answered), "a low-confidence answer to our own question was re-asked"


# --- §6 walkthrough rows: guards that were read but not executed (Task 4.2) ---


async def test_out_of_scope_says_what_is_covered_and_returns_to_the_task(make):
    """Spec §6.28. One sentence on scope, then back to the task - and nothing improvised
    from model knowledge, which is what an out-of-scope answer would have to be."""
    orch, s = make([j1(intent="out_of_scope")])
    o = await orch.handle_text(s, "can you help me buy a flat instead?")

    assert isinstance(o, Answered)
    assert "not buying" in o.spoken and "Bengaluru" in o.spoken
    assert o.spoken.rstrip().endswith("?")  # it hands the turn back
    assert s.shortlist.is_empty()  # no arbitrary slice was produced to fill the silence


async def test_asking_for_the_owners_number_gets_the_labelled_placeholder(make):
    """Spec §6.33. The only contact in the system is the demo placeholder, and the reply
    says so rather than implying a real number is being withheld."""
    orch, s = make([j1(intent="owner_contact")])
    o = await orch.handle_text(s, "what is the owner's phone number?")

    assert isinstance(o, Answered)
    assert "999999999" in o.spoken
    assert "no real owner details" in o.spoken


async def test_no_constraints_at_all_asks_for_the_two_that_narrow_most(make):
    """Spec §6.31. "Just show me something" must not return an arbitrary slice dressed as
    a shortlist - it asks for a budget and a locality."""
    orch, s = make([j1(edits=[])])
    o = await orch.handle_text(s, "just show me something")

    assert isinstance(o, NeedsInput)
    assert o.field == "constraints"
    assert "budget" in o.question and "locality" in o.question
    assert s.shortlist.is_empty()


async def test_when_every_shortlisted_listing_is_withdrawn_it_says_so_and_backfills_nothing(
    make,
):
    """Spec §6.39. Distinct from §6.4's single removal: when the whole shortlist goes, the
    renter is returned to constraint collection rather than handed listings they never
    heard chosen."""
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]),
            j1(intent="confirm_yes"),
            j1(edits=[]),
        ]
    )
    await orch.handle_text(s, "Koramangala")
    o = await orch.handle_text(s, "yes")
    heard = list(o.view_model.shortlist.order)
    assert heard, "the fixture must produce a shortlist for this row to mean anything"

    for lid in heard:
        orch.availability.set(lid, False)
    o2 = await orch.handle_text(s, "show me again")

    assert isinstance(o2, Empty)
    assert "no longer available" in o2.spoken or "all" in o2.spoken.lower()
    assert s.shortlist.is_empty()  # nothing was backfilled from outside the shortlist


async def test_an_ordinal_is_re_anchored_when_the_list_changed_since_it_was_heard(make):
    """Spec §6.30. The ordinal resolves against `last_read_order` - what the renter last
    HEARD - and when that no longer matches the current order the listing is named back
    for confirmation instead of being acted on."""
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]),
            j1(intent="confirm_yes"),
            j1(reference=2),
        ]
    )
    await orch.handle_text(s, "Koramangala")
    o = await orch.handle_text(s, "yes")
    assert len(o.view_model.shortlist.order) >= 2, "need two listings to reorder"

    # The list moved under the renter since they last heard it read out. `Shortlist.order`
    # is a property that rebuilds its list on every read, so the stale side has to be
    # `last_read_order` - the one field that actually persists what was spoken.
    s.last_read_order = list(reversed(s.last_read_order))
    assert s.shortlist.order != s.last_read_order

    o2 = await orch.handle_text(s, "the second one")

    assert isinstance(o2, NeedsInput)
    assert o2.field == "reference"
    assert o2.question.startswith("Do you mean")
    assert o2.options == ["yes", "no"]
    # It re-anchors on what they heard second, not on what is now second.
    assert s.focus_listing_id == s.last_read_order[1]


async def test_job1_hears_digit_ordinals_as_words(make):
    """The orchestrator normalises "the 1st 1" before routing and before Job 1 sees it."""
    orch, session = make([Job1Down("down")])
    seen = []
    real = orch.job1.extract

    async def recording(text, current):
        seen.append(text)
        return await real(text, current)

    orch.job1.extract = recording
    await orch.handle_text(session, "Book a visit for the 1st 1.")
    assert seen == ["Book a visit for the first one."]


async def test_a_locality_question_carries_its_candidate_names_as_options(make):
    from scout.conversation.job1 import Ambiguity

    q = "Khyakpuram isn't covered. Did you mean KR Puram, Shampura or Sagayapuram?"
    amb = Ambiguity(
        field="locality",
        heard="Khyakpuram",
        question=q,
        options=["KR Puram", "Shampura", "Sagayapuram"],
    )
    orch, s = make([j1(ambiguities=[amb])])[:2]
    o = await orch.handle_text(s, "2 BHK in Khyakpuram")
    assert isinstance(o, NeedsInput) and o.field == "locality"
    assert o.options == ["KR Puram", "Shampura", "Sagayapuram"]


async def test_the_clear_parts_of_a_sentence_survive_a_question_about_the_rest(make):
    """Production, 2026-09-17: "2 BHK in Khyakpuram" asked which locality was meant and threw
    the 2 BHK away, so the readback was "in KR Puram" alone and the first result a 3BHK."""
    from scout.conversation.job1 import Ambiguity

    amb = Ambiguity(
        field="locality",
        heard="Koramangla",
        question="Koramangla isn't covered. Did you mean Koramangala?",
        options=["Koramangala"],
    )
    orch, s = make(
        [
            j1(
                edits=[
                    ConstraintEdit("bhk_type", "set", "2BHK"),
                    ConstraintEdit("rent_max", "set", 40000),
                ],
                ambiguities=[amb],
            ),
            j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]),
        ]
    )
    o1 = await orch.handle_text(s, "2 BHK in Koramangla under forty thousand")
    assert isinstance(o1, NeedsInput) and o1.field == "locality"

    o2 = await orch.handle_text(s, "Koramangala")
    assert isinstance(o2, NeedsInput) and o2.field == "constraints_readback"
    assert "2BHK" in o2.question and "40,000" in o2.question and "Koramangala" in o2.question


async def test_a_spent_question_budget_still_keeps_the_clear_parts(make):
    from scout.conversation.job1 import Ambiguity

    amb = Ambiguity(field="locality", heard="Koramangla", question="Did you mean Koramangala?")
    orch, s = make([j1(edits=[ConstraintEdit("bhk_type", "set", "2BHK")], ambiguities=[amb])])
    s.constraints = s.constraints.with_(localities=("Koramangala",))
    s.clarifying_asked = orch.settings.max_clarifying_questions
    await orch.handle_text(s, "2 BHK in Koramangla")
    assert "2BHK" in "; ".join(s.constraints.readback())


async def _empty(make, edits):
    orch, s = make([j1(edits=edits), j1(intent="confirm_yes")])
    await orch.handle_text(s, "requirements")
    o = await orch.handle_text(s, "yes")
    assert isinstance(o, Empty)
    return o


async def test_an_empty_result_names_what_was_not_found_and_nearby_places_that_have_it(make):
    """Production, 2026-09-17: "I found nothing matching your localities in Indiranagar"."""
    o = await _empty(
        make,
        [
            ConstraintEdit("localities", "add", "Koramangala"),
            ConstraintEdit("bhk_type", "set", "3BHK"),
            ConstraintEdit("rent_max", "set", 70000),
        ],
    )
    assert o.spoken.startswith("No 3BHK under ₹70,000 in Koramangala."), o.spoken
    assert "matching your" not in o.spoken
    assert "HSR Layout" in o.spoken, "the 3BHK at ₹55,000 is in HSR Layout: locality binds"


async def test_nearby_places_are_not_suggested_when_the_place_is_not_what_binds(make):
    o = await _empty(
        make,
        [
            ConstraintEdit("localities", "add", "Koramangala"),
            ConstraintEdit("bhk_type", "set", "2BHK"),
            ConstraintEdit("rent_max", "set", 30000),
        ],
    )
    assert o.spoken.startswith("No 2BHK under ₹30,000 in Koramangala."), o.spoken
    assert "HSR Layout" not in o.spoken and "nearby" not in o.spoken
    assert "₹36,000" in o.spoken


async def test_listings_that_do_not_mention_a_detail_are_offered_in_plain_words(make):
    """Production, 2026-09-17: "...or include the listings where that detail is not stated."
    for a hospital requirement."""
    o = await _empty(
        make,
        [
            ConstraintEdit("localities", "add", "Koramangala"),
            ConstraintEdit("amenities_required", "add", "hospital"),
        ],
    )
    assert "not stated" not in o.spoken and "that detail" not in o.spoken
    assert "hospital" in o.spoken and "2 listings there don't mention it" in o.spoken, o.spoken


async def test_replay_tcpalya_is_read_back_as_tc_palya_with_no_question(make):
    """Production, 2026-09-17, conv 3: "I'm in TCPalya." -> "TCPalya isn't covered"."""
    from scout.conversation.job1 import Job1

    class Model:
        async def complete_json(self, system, user, name, schema):
            return {
                "intent": "set_preferences",
                "edits": [
                    {"field": "bhk_type", "op": "set", "value": "2BHK"},
                    {"field": "localities", "op": "add", "value": "TCPalya"},
                    {"field": "rent_max", "op": "set", "value": "50,000"},
                ],
                "ambiguities": [],
                "reference": None,
                "email": None,
                "code": None,
                "slot_choice": None,
            }

    orch, s = make([])
    orch.job1 = Job1(Model(), ["Koramangala", "S.G Palya", "T.C Palya", "TC Palya"])
    o = await orch.handle_text(s, "2 BHK in TCPalya under 50,000")
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback", o
    assert "in TC Palya;" in o.question and "T.C Palya" not in o.question, o.question
    assert set(s.constraints.localities) == {"T.C Palya", "TC Palya"}


# --- B1, B2, B3 (voice fix batch 2026-09-17): remembering her own questions ---

TC_OPTIONS = ["T.C Palya", "TC Palya", "S.G Palya"]


def _did_you_mean(options, heard="TCPalya"):
    from scout.conversation.job1 import Ambiguity

    names = ", ".join(options[:-1]) + f" or {options[-1]}" if len(options) > 1 else options[0]
    return Ambiguity(
        field="locality",
        heard=heard,
        question=f"{heard} isn't covered. Did you mean {names}?",
        options=list(options),
    )


def _with_places(orch, *names):
    for n in names:
        orch.store.manifest.localities[n] = 1


async def _asked_which(make, options, *later, first_edits=()):
    orch, s = make(
        [
            j1(
                edits=[ConstraintEdit("bhk_type", "set", "2BHK"), *first_edits],
                ambiguities=[_did_you_mean(options)],
            ),
            *later,
        ]
    )
    _with_places(orch, "T.C Palya", "TC Palya", "S.G Palya")
    o = await orch.handle_text(s, "2 BHK in TCPalya")
    assert isinstance(o, NeedsInput) and o.field == "locality" and o.options == list(options)
    return orch, s


@pytest.mark.parametrize("said", ["The 2nd 1, T C", "the second one", "TC Palya", "T C Palya."])
async def test_an_answer_to_did_you_mean_picks_from_the_names_offered(make, said):
    """B1, production 2026-09-17: "The 2nd 1, T C" after "Did you mean T.C Palya, TC Palya or
    S.G Palya?" got "Which one do you mean?"."""
    orch, s = await _asked_which(make, TC_OPTIONS)
    asked = s.clarifying_asked

    o = await orch.handle_text(s, said)

    assert isinstance(o, NeedsInput) and o.field == "constraints_readback", o
    assert "in TC Palya;" in o.question and "2BHK" in o.question, o.question
    assert set(s.constraints.localities) == {"T.C Palya", "TC Palya"}
    assert orch.job1.results == [], "Job 1 was not needed to read an answer to our own question"
    assert s.clarifying_asked == asked


async def test_a_name_that_was_not_offered_is_read_by_job1_as_usual(make):
    """B1: "I mentioned Dommasandra." after "Did you mean Domluru or Domlur?" matches no offer,
    so it is a sentence like any other; the pending question is dropped."""
    orch, s = await _asked_which(
        make,
        ["Domluru", "Domlur"],
        j1(edits=[ConstraintEdit("localities", "add", "Dommasandra")]),
    )

    o = await orch.handle_text(s, "I mentioned Dommasandra.")

    assert orch.job1.results == []
    assert s.constraints.localities == ("Dommasandra",)
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback"


@pytest.mark.parametrize("said", ["yes", "Yes.", "no"])
async def test_a_bare_yes_or_no_to_several_names_asks_again_with_the_same_names(make, said):
    orch, s = await _asked_which(make, TC_OPTIONS)

    o = await orch.handle_text(s, said)

    assert isinstance(o, NeedsInput) and o.field == "locality"
    assert o.options == TC_OPTIONS
    assert all(n in o.spoken for n in TC_OPTIONS)
    assert not s.constraints.localities


async def test_a_bare_yes_to_one_name_takes_it(make):
    orch, s = await _asked_which(make, ["TC Palya"])

    o = await orch.handle_text(s, "yes")

    assert isinstance(o, NeedsInput) and o.field == "constraints_readback"
    assert "TC Palya" in o.question and s.pending is not None


async def test_the_pending_choice_is_dropped_once_answered(make):
    orch, s = await _asked_which(make, TC_OPTIONS, j1(intent="confirm_yes"))
    await orch.handle_text(s, "the second one")

    o = await orch.handle_text(s, "yes")

    assert isinstance(o, (Answered, Empty))
    assert s.pending is None


async def test_no_with_a_correction_to_the_readback_applies_it_and_reads_back_again(make):
    """B2, production 2026-09-17: "No. I mentioned Dommasandra." -> "What should I change?"."""
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "HSR Layout")]),
            j1(
                intent="confirm_no",
                edits=[
                    ConstraintEdit("localities", "remove", "HSR Layout"),
                    ConstraintEdit("localities", "add", "Koramangala"),
                ],
            ),
        ]
    )
    await orch.handle_text(s, "in HSR Layout")

    o = await orch.handle_text(s, "No. I mentioned Koramangala.")

    assert isinstance(o, NeedsInput) and o.field == "constraints_readback", o
    assert "Koramangala" in o.question and "HSR" not in o.question
    assert s.constraints.localities == ("Koramangala",)


async def test_a_bare_no_to_the_readback_still_asks_what_to_change(make):
    orch, s = make(
        [j1(edits=[ConstraintEdit("localities", "add", "HSR Layout")]), j1(intent="confirm_no")]
    )
    await orch.handle_text(s, "in HSR Layout")
    o = await orch.handle_text(s, "no")
    assert isinstance(o, NeedsInput) and o.question == "What should I change?"


async def test_removing_the_only_locality_asks_which_locality(make):
    """B3, production 2026-09-17: "Not Domesandra." -> "Just to confirm — a 3BHK; rent up to
    ₹70,000." — a whole-city search she never asked for."""
    orch, s = make(
        [
            j1(
                edits=[
                    ConstraintEdit("localities", "add", "HSR Layout"),
                    ConstraintEdit("bhk_type", "set", "3BHK"),
                ]
            ),
            j1(edits=[ConstraintEdit("localities", "remove", "HSR Layout")]),
        ]
    )
    await orch.handle_text(s, "3 BHK in HSR Layout")

    o = await orch.handle_text(s, "Not HSR Layout.")

    assert isinstance(o, NeedsInput) and o.field == "locality", o
    assert "locality" in o.spoken.lower() and "Just to confirm" not in o.spoken
    assert s.clarifying_asked == 1
    assert not s.constraints.localities and s.constraints.bhk_type is not None
    assert s.pending is None


@pytest.mark.parametrize(
    "said", ["TC Palya, and make it under 40,000", "Not TC Palya, S.G Palya is wrong too."]
)
async def test_more_than_a_choice_is_left_to_job1(make, said):
    orch, s = await _asked_which(make, TC_OPTIONS, j1(edits=[]))

    await orch.handle_text(s, said)

    assert orch.job1.results == [], "Job 1 was skipped for a sentence that says more"
    assert type(s.pending).__name__ != "AwaitLocalityChoice"


async def test_clearing_every_locality_on_purpose_is_not_asked_about(make):
    """B3 is about removing the last place; "anywhere" (a clear) belongs to F1."""
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "HSR Layout")]),
            j1(edits=[ConstraintEdit("localities", "clear", None)]),
        ]
    )
    await orch.handle_text(s, "in HSR Layout")
    o = await orch.handle_text(s, "anywhere is fine")
    assert not (isinstance(o, NeedsInput) and o.field == "locality")


# --- E2 (voice fix batch 2026-09-17): parking and lift ---


def _job1_hearing(*edits):
    """The real Job 1 over a model that returns these edits, as production's Gemini did."""
    from scout.conversation.job1 import Job1

    class Model:
        async def complete_json(self, system, user, name, schema):
            return {
                "intent": "set_preferences",
                "edits": [{"field": f, "op": op, "value": v} for f, op, v in edits],
                "ambiguities": [],
                "reference": None,
                "email": None,
                "code": None,
                "slot_choice": None,
            }

    return Job1(Model(), ["Koramangala", "HSR Layout"])


def _kinds_not_stated(orch):
    """The real bundle: no listing states the kind of parking, only whether there is any."""
    from dataclasses import replace

    for lid, listing in list(orch.store.listings.items()):
        facts = dict(listing.facts)
        facts["parking"] = replace(facts["parking"], value=None)
        orch.store.listings[lid] = replace(listing, facts=facts)


async def test_replay_a_parking_facility_is_read_back_with_no_question(make):
    """Production, 2026-09-17: "...with a parking facility." -> "I didn't follow the parking
    required — I heard 'true'. What should I use?"; "I'm saying I need parking also." -> the
    same with 'yes', a loop."""
    orch, s = make([])
    orch.job1 = _job1_hearing(
        ("bhk_type", "set", "2BHK"),
        ("localities", "add", "HSR Layout"),
        ("rent_max", "set", "50,000"),
        ("parking_required", "set", "true"),
    )
    o = await orch.handle_text(s, "2 BHK in HSR Layout under 50,000 with a parking facility")
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback", o
    assert "with parking" in o.question, o.question
    assert "didn't follow" not in o.question

    orch.job1 = _job1_hearing(("parking_required", "set", "yes"))
    o2 = await orch.handle_text(s, "I'm saying I need parking also.")
    assert isinstance(o2, NeedsInput) and o2.field == "constraints_readback", o2
    assert "with parking" in o2.question and "didn't follow" not in o2.question


async def test_parking_finds_listings_that_say_parking_is_available(make):
    orch, s = make([j1(intent="confirm_yes")])
    _kinds_not_stated(orch)
    orch.job1 = _job1_hearing(
        ("localities", "add", "Koramangala"), ("parking_required", "set", "yes")
    )
    await orch.handle_text(s, "in Koramangala with parking")
    orch.job1 = ScriptedJob1([j1(intent="confirm_yes")])
    o = await orch.handle_text(s, "yes")
    assert isinstance(o, Answered), o
    assert o.view_model.shortlist.order == ["kor-001"]


async def test_a_named_kind_of_parking_is_explained_once_when_no_listing_states_kinds(make):
    orch, s = make([])
    _kinds_not_stated(orch)
    orch.job1 = _job1_hearing(
        ("localities", "add", "Koramangala"), ("parking_required", "set", "car parking")
    )
    o = await orch.handle_text(s, "in Koramangala with car parking")
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback", o
    assert "car or a bike" in o.spoken and "with parking" in o.spoken, o.spoken

    orch.job1 = _job1_hearing(("parking_required", "set", "bike parking"))
    o2 = await orch.handle_text(s, "bike parking actually")
    assert "car or a bike" not in o2.spoken, "said once, not every turn"


async def test_a_named_kind_is_not_explained_when_listings_state_kinds(make):
    orch, s = make([])
    orch.job1 = _job1_hearing(
        ("localities", "add", "Koramangala"), ("parking_required", "set", "car parking")
    )
    o = await orch.handle_text(s, "in Koramangala with car parking")
    assert "car or a bike" not in o.spoken


async def test_a_lift_is_said_to_be_unstated_rather_than_filtering_everything_out(make):
    """Production, 2026-09-17: "does this have a lift facility?" -> Empty. No listing states a
    lift, so a lift requirement can only ever empty the shortlist."""
    orch, s = make([])
    orch.job1 = _job1_hearing(
        ("localities", "add", "Koramangala"), ("lift_required", "set", "true")
    )
    o = await orch.handle_text(s, "in Koramangala with a lift")
    assert isinstance(o, NeedsInput) and o.field == "constraints_readback", o
    assert "don't say" in o.spoken and "lift" in o.spoken, o.spoken
    assert "with a lift" not in o.question
    assert not s.constraints.lift_required

    orch.job1 = ScriptedJob1([j1(intent="confirm_yes")])
    first = await orch.handle_text(s, "yes")
    assert isinstance(first, Answered), first

    orch.job1 = _job1_hearing(("lift_required", "set", "yes"))
    o2 = await orch.handle_text(s, "only ones with a lift")
    assert isinstance(o2, Answered), o2
    assert "lift" in o2.spoken and "don't say" in o2.spoken, o2.spoken
    assert s.shortlist.order == first.view_model.shortlist.order


async def test_a_lift_alone_on_a_first_turn_still_asks_for_a_start(make):
    orch, s = make([])
    orch.job1 = _job1_hearing(("lift_required", "set", "true"))
    o = await orch.handle_text(s, "with a lift")
    assert isinstance(o, NeedsInput) and o.field == "constraints", o
    assert "lift" in o.spoken


async def test_the_a3_sentence_with_a_shortlist_on_screen_applies_its_requirements(make):
    """A3 replay, end to end (batch review, 2026-09-17: only its routing was tested). With a
    shortlist on screen the heard sentence reaches Job 1 and its requirements are applied;
    it is not explained (lane B, which this orchestrator cannot even run: job2=None)."""
    orch, s = make(
        [
            j1(edits=[ConstraintEdit("localities", "add", "Koramangala")]),
            j1(intent="confirm_yes"),
            j1(
                intent="refine",
                edits=[
                    ConstraintEdit("square_footage_min", "set", "1500"),
                    ConstraintEdit("furnishing", "set", "fully furnished"),
                    ConstraintEdit("bhk_type", "set", "3BHK"),
                    ConstraintEdit("parking_required", "set", "parking facility"),
                    ConstraintEdit("lift_required", "set", "true"),
                ],
            ),
        ]
    )
    await orch.handle_text(s, "in Koramangala")
    shown = await orch.handle_text(s, "yes")
    assert isinstance(shown, Answered) and not s.shortlist.is_empty()

    heard = (
        "I don't know why you did not listen to me when I asked you to stop. Anyways, here "
        "I'm giving you a further filtering options. The size should be at least 1,500 "
        "square feet. It should be fully furnished. 3 BHK or more. Should be having a "
        "parking facility. And it should have lift facility."
    )
    o = await orch.handle_text(s, heard)

    assert orch.job1.results == [], "Job 1 read the requirements"
    assert not (isinstance(o, Failed) and o.capability == "explanation"), o
    c = s.constraints
    assert c.square_footage_min == 1500 and c.furnishing is not None and c.bhk_type is not None
    assert c.parking_required is True and not c.lift_required
    assert "lift" in o.spoken and "_" not in o.spoken, o.spoken
