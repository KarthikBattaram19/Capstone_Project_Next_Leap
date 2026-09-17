"""F1 (voice fix batch, 2026-09-17): "best location" and "better listings".

Production: "My budget is 1 lakh. I leave it to you to give me the best location. In
Bangalore." was read back as "rent up to ₹1,00,000" and searched the whole city without a
word about how 1,856 listings were ordered; "Are there not any better listings?" then got an
explanation of listing 1.
"""

import pytest

from scout.config import Settings
from scout.contract.outcome import Answered, NeedsInput
from scout.conversation.job1 import Job1Result
from scout.conversation.orchestrator import NullSpeaker, TurnOrchestrator
from scout.conversation.session import AwaitArea, ConfirmConstraints, SessionManager
from scout.domain.constraints import ConstraintEdit
from scout.domain.osm import OsmQuery
from scout.engines.availability import AvailabilityRegister
from scout.platform.artefacts import ArtefactStore

AREA_Q = "Bengaluru is big — is there an area you prefer, or somewhere you commute to?"


class ScriptedJob1:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[str] = []

    async def extract(self, text, current):
        self.calls.append(text)
        return self.results.pop(0)


def j1(intent="set_preferences", edits=()):
    return Job1Result(
        intent=intent,
        edits=list(edits),
        ambiguities=[],
        reference=None,
        email=None,
        code=None,
        slot_choice=None,
    )


@pytest.fixture
def make(bundle_min):
    def build(results):
        store = ArtefactStore.load(bundle_min)
        settings = Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_min
        )
        job1 = ScriptedJob1(results)
        orch = TurnOrchestrator(
            store,
            settings,
            job1=job1,
            job2=None,
            availability=AvailabilityRegister(store),
            speaker_factory=lambda: NullSpeaker(),
        )
        return orch, SessionManager(60).create(), job1

    return build


BUDGET = j1(edits=[ConstraintEdit("rent_max", "set", 100000)])
SENTENCE = "My budget is 1 lakh. I leave it to you to give me the best location. In Bangalore."


async def test_no_place_and_no_commute_asks_for_an_area_before_the_readback(make):
    orch, s, _ = make([BUDGET])
    o = await orch.handle_text(s, SENTENCE)
    assert isinstance(o, NeedsInput)
    assert o.question == AREA_Q and o.spoken == AREA_Q
    assert isinstance(s.pending, AwaitArea)
    assert s.clarifying_asked == 1
    assert s.shortlist.is_empty()


async def test_anywhere_searches_the_city_and_says_the_order(make):
    orch, s, job1 = make([BUDGET, j1(intent="confirm_yes")])
    await orch.handle_text(s, SENTENCE)
    rb = await orch.handle_text(s, "Anywhere is fine.")
    assert job1.calls == [SENTENCE]  # the answer is read in code, not by Job 1
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"
    assert "anywhere in Bengaluru" in rb.question
    assert isinstance(s.pending, ConfirmConstraints)

    o = await orch.handle_text(s, "yes")
    assert isinstance(o, Answered)
    assert "across Bengaluru, cheapest first" in o.spoken
    assert o.view_model.shortlist.order == ["kor-002", "kor-001", "hsr-001"]


@pytest.mark.parametrize("answer", ["whole city", "Anywhere in Bangalore", "no preference"])
async def test_other_ways_of_saying_anywhere(make, answer):
    orch, s, job1 = make([BUDGET])
    await orch.handle_text(s, SENTENCE)
    rb = await orch.handle_text(s, answer)
    assert len(job1.calls) == 1
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"


async def test_a_place_in_answer_is_read_by_job1_and_read_back(make):
    orch, s, _ = make([BUDGET, j1(edits=[ConstraintEdit("localities", "add", "Koramangala")])])
    await orch.handle_text(s, SENTENCE)
    rb = await orch.handle_text(s, "Koramangala")
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"
    assert "Koramangala" in rb.question
    assert s.clarifying_asked == 1


async def test_the_area_question_is_asked_once(make):
    orch, s, _ = make([BUDGET, j1(edits=[ConstraintEdit("bhk_type", "set", "2BHK")])])
    await orch.handle_text(s, SENTENCE)
    rb = await orch.handle_text(s, "a 2BHK please")
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"
    assert "anywhere in Bengaluru" in rb.question


async def test_anywhere_in_the_first_sentence_is_not_asked_about(make):
    orch, s, _ = make([BUDGET])
    rb = await orch.handle_text(s, "anywhere in Bengaluru, budget 1 lakh")
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"
    assert s.clarifying_asked == 0


async def test_a_commute_point_is_enough(make):
    orch, s, _ = make(
        [j1(edits=[BUDGET.edits[0], ConstraintEdit("commute", "set", "Manyata Tech Park")])]
    )
    rb = await orch.handle_text(s, "budget 1 lakh, I work at Manyata Tech Park")
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"


async def _city_shortlist(make, extra=()):
    orch, s, job1 = make([BUDGET, j1(intent="confirm_yes"), *extra])
    await orch.handle_text(s, SENTENCE)
    await orch.handle_text(s, "anywhere")
    await orch.handle_text(s, "yes")
    return orch, s, job1


async def test_better_listings_explains_the_order_and_offers_others(make):
    orch, s, job1 = await _city_shortlist(make)
    before = list(s.shortlist.order)
    o = await orch.handle_text(s, "Okay. Are there not any better listings?")
    assert isinstance(o, NeedsInput) and o.field == "order"
    assert "cheapest first" in o.spoken
    assert "largest first" in o.spoken and "nearest the metro" in o.spoken
    assert o.options == ["largest first", "nearest metro first"]
    assert len(job1.calls) == 2  # the first sentence and "yes"
    assert s.shortlist.order == before


async def test_largest_first_reorders_the_shortlist(make):
    orch, s, job1 = await _city_shortlist(make)
    o = await orch.handle_text(s, "largest first")
    assert isinstance(o, Answered)
    assert o.view_model.shortlist.order == ["hsr-001", "kor-001", "kor-002"]
    assert s.last_read_order == ["hsr-001", "kor-001", "kor-002"]
    assert "largest first" in o.spoken
    assert len(job1.calls) == 2
    again = await orch.handle_text(s, "any better listings?")
    assert "largest first" in again.spoken and "cheapest first" in again.spoken


async def test_nearest_metro_first_is_not_an_explanation(make):
    orch, s, _ = await _city_shortlist(make)
    o = await orch.handle_text(s, "nearest metro first")
    assert isinstance(o, Answered)  # job2 is None: lane B would have Failed
    order = o.view_model.shortlist.order
    assert order == ["kor-001", "hsr-001", "kor-002"]  # no metro distance goes last
    assert orch.store.osm("kor-002", OsmQuery.NEAREST_METRO).distance_m is None


async def test_with_a_commute_point_nearest_to_work_is_offered(make):
    orch, s, _ = make(
        [
            j1(edits=[BUDGET.edits[0], ConstraintEdit("commute", "set", "Manyata Tech Park")]),
            j1(intent="confirm_yes"),
        ]
    )
    await orch.handle_text(s, "budget 1 lakh, I work at Manyata Tech Park")
    await orch.handle_text(s, "yes")
    o = await orch.handle_text(s, "are there better options?")
    assert o.options == ["largest first", "nearest metro first", "nearest to work first"]
    sorted_ = await orch.handle_text(s, "nearest to work first")
    point = s.constraints.commute
    dist = [orch.commute.to_point(i, point).value.metres for i in s.shortlist.order]
    assert isinstance(sorted_, Answered) and dist == sorted(dist)


async def test_a_better_listing_with_a_requirement_is_a_search(make):
    orch, s, job1 = await _city_shortlist(
        make, extra=[j1(intent="refine", edits=[ConstraintEdit("rent_max", "set", 30000)])]
    )
    await orch.handle_text(s, "show me better listings under 30,000")
    assert len(job1.calls) == 3
    assert s.constraints.rent_max == 30000


async def _city_readback(make, extra=()):
    orch, s, job1 = make([BUDGET, *extra])
    await orch.handle_text(s, SENTENCE)
    rb = await orch.handle_text(s, "anywhere")
    assert isinstance(rb, NeedsInput) and rb.field == "constraints_readback"
    return orch, s, job1, rb


async def test_better_listings_during_the_readback_says_the_order_and_asks_again(make):
    """Production replay (2026-09-17, after 3c69bbf): the readback "rent up to ₹1,00,000;
    anywhere in Bengaluru. Is that right?" was answered "Are there not any better listings?"
    and she said "Sorry, I didn't follow that." The order is said, the readback is asked
    again with its buttons, and "yes" still searches."""
    orch, s, job1, rb = await _city_readback(make, extra=[j1(intent="confirm_yes")])
    o = await orch.handle_text(s, "Are there not any better listings?")
    assert isinstance(o, NeedsInput), f"got {o.kind}: {o.spoken}"
    assert "didn't follow" not in o.spoken
    assert "no rating or review" in o.spoken and "cheapest first" in o.spoken, o.spoken
    assert "largest first" in o.spoken and "nearest the metro" in o.spoken, o.spoken
    assert o.spoken.endswith(rb.question), o.spoken
    assert o.field == "constraints_readback" and o.options == ["yes", "no"]
    assert o.question == o.spoken
    assert isinstance(s.pending, ConfirmConstraints)
    assert len(job1.calls) == 1  # read in code, not by Job 1
    assert s.shortlist.is_empty()

    done = await orch.handle_text(s, "yes")
    assert isinstance(done, Answered), f"got {done.kind}: {done.spoken}"
    assert "across Bengaluru, cheapest first" in done.spoken


async def test_an_unclear_turn_during_the_readback_keeps_it_pending(make):
    """Any other off-script turn while the readback waits leaves it waiting: "yes" after it
    still runs the search."""
    orch, s, _, _ = await _city_readback(
        make, extra=[j1(intent="unclear"), j1(intent="confirm_yes")]
    )
    o = await orch.handle_text(s, "hmm what was that")
    assert isinstance(o, NeedsInput) and o.field == "unclear"
    assert isinstance(s.pending, ConfirmConstraints)
    done = await orch.handle_text(s, "yes")
    assert isinstance(done, Answered), f"got {done.kind}: {done.spoken}"
