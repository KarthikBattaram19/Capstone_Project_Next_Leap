import pytest

from scout.config import Settings
from scout.contract.outcome import Answered, Empty, Failed, NeedsInput
from scout.conversation.job1 import Job1Down, Job1Result
from scout.conversation.orchestrator import NullSpeaker, TurnOrchestrator
from scout.conversation.session import SessionManager
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
