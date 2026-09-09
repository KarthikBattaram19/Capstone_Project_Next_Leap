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
