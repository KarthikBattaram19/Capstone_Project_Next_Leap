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
    await orch.handle_text(s, "anything under five thousand")
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
            j1(edits=[ConstraintEdit("rent_min", "set", 30000)]),
            j1(edits=[ConstraintEdit("rent_max", "set", 25000)]),
        ]
    )
    await orch.handle_text(s, "only above 30k")
    o = await orch.handle_text(s, "under 25k")
    assert isinstance(o, NeedsInput)
    assert s.clarifying_asked == 1
    assert s.constraints.rent_max is None


async def test_budget_exhausted_proceeds_provisionally_and_says_so(make):
    amb = [
        type(
            "A",
            (),
            {"field": "rent_max", "heard": "thirty five", "question": "Did you mean ₹35,000?"},
        )
    ]
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
    return j1(intent="unclear", edits=list(edits))


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
