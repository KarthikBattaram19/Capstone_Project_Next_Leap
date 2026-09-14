"""Lane B: the opener is spoken first, only bound claims reach the renter, Job 2 down degrades."""

import pytest

from scout.config import Settings
from scout.contract.outcome import Answered, Degraded, NeedsInput
from scout.conversation.job1 import Job1Result
from scout.conversation.job2 import Job2Down, Job2Sentence
from scout.conversation.orchestrator import TurnOrchestrator
from scout.conversation.session import SessionManager
from scout.engines.availability import AvailabilityRegister
from scout.platform.artefacts import ArtefactStore


class ScriptedJob1:
    def __init__(self, results):
        self.results = list(results)

    async def extract(self, text, current):
        return self.results.pop(0)


class ScriptedJob2:
    """Yields the scripted sentences, or raises whatever it was given."""

    def __init__(self, sentences, raises=None):
        self.sentences = sentences
        self.raises = raises
        self.last_gaps: list[str] = []

    async def explain(self, bundle, question):
        if self.raises is not None:
            raise self.raises
        for s in self.sentences:
            yield s


class RecordingSpeaker:
    def __init__(self):
        self.said: list[str] = []

    async def speak(self, sentences):
        async for s in sentences:
            self.said.append(s)

    async def cancel(self):
        return None


@pytest.fixture
def make(bundle_min):
    def build(job2, job1_results=()):
        store = ArtefactStore.load(bundle_min)
        settings = Settings(
            _env_file=None, cors_allowed_origins="http://localhost:3000", bundle_dir=bundle_min
        )
        speaker = RecordingSpeaker()
        orch = TurnOrchestrator(
            store,
            settings,
            job1=ScriptedJob1(job1_results),
            job2=job2,
            availability=AvailabilityRegister(store),
            speaker_factory=lambda: speaker,
        )
        session = SessionManager(60).create()
        lid = next(x for x in store.listings if store.listings[x].locality == "Koramangala")
        session.last_read_order = [lid]
        session.shortlist = _one(store, lid)
        return orch, session, speaker, lid

    return build


def _one(store, lid):
    from scout.domain.shortlist import Shortlist, ShortlistEntry

    return Shortlist(matched=(ShortlistEntry(lid, 1),))


async def test_only_bound_claims_reach_the_renter_and_the_opener_is_spoken_first(make):
    def sentences(lid):
        return [
            Job2Sentence(
                "Rent is stated in the dataset for this listing.", [f"dataset:{lid}:rent"]
            ),
            Job2Sentence(
                "The guide describes the blocks near Forum Mall as the noisiest at night.",
                ["guide:koramangala-0-1"],
            ),
            Job2Sentence("The area is very safe.", ["guide:made-up"]),
        ]

    orch, session, speaker, lid = make(ScriptedJob2([]))
    orch.job2 = ScriptedJob2(sentences(lid))

    out = await orch.handle_text(session, "why did you pick this one?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    exp = out.view_model.explanation
    assert exp is not None
    assert len(exp.claims) == 2, [c.text for c in exp.claims]
    cited = {r for c in exp.claims for r in c.citation_refs}
    assert cited <= {s.ref for s in exp.sources}, "a claim cites something not in Sources"
    assert speaker.said[0] == exp.opener, f"the opener was not spoken first: {speaker.said}"
    assert session.focus_listing_id == lid
    assert out.view_model.snapshot is not None


async def test_job2_down_is_degraded_not_a_substitute(make, capsys):
    orch, session, speaker, _lid = make(ScriptedJob2([], raises=Job2Down("provider down")))
    out = await orch.handle_text(session, "why this one?")
    await session.speaking

    assert isinstance(out, Degraded)
    assert out.missing == ["explanation"]
    assert out.view_model.explanation is None
    assert speaker.said, "the opener must still be spoken when the explanation is withheld"
    # The reason is on the outcome and in the log, so a whole degraded suite run cannot
    # pass for a code defect (2026-09-14: a revoked key looked like 13 grounding failures).
    assert "provider down" in out.why
    assert "job2 down: provider down" in capsys.readouterr().err


class ClosableJob1Client:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


async def test_aclose_closes_both_provider_clients(make):
    job2 = ScriptedJob2([])
    job2.closed = False

    async def close_job2():
        job2.closed = True

    job2.aclose = close_job2
    orch, _session, _speaker, _lid = make(job2)
    orch.job1.client = ClosableJob1Client()
    await orch.aclose()
    assert orch.job1.client.closed and job2.closed


async def test_aclose_tolerates_clients_that_cannot_be_closed(make):
    orch, _session, _speaker, _lid = make(ScriptedJob2([]))  # ScriptedJob1 has no client
    await orch.aclose()


async def test_why_with_no_shortlist_is_lane_a(make):
    j1 = Job1Result(
        intent="unclear",
        edits=[],
        ambiguities=[],
        reference=None,
        email=None,
        code=None,
        slot_choice=None,
    )
    orch, session, _speaker, _ = make(ScriptedJob2([]), job1_results=[j1])
    session.last_read_order = []
    session.shortlist = type(session.shortlist)()  # empty again

    out = await orch.handle_text(session, "why?")
    assert isinstance(out, NeedsInput), f"got {out.kind}: {out.spoken}"


async def test_the_turn_records_what_the_assembler_dropped(make):
    """Per case, not per sentence: JOB2_SCORES.md asks for a per-case drop count.

    The counts accumulate on the session, so a suite case that asks two questions reports
    both turns together and a fresh case starts at zero.
    """
    orch, session, _speaker, lid = make(ScriptedJob2([]))
    orch.job2 = ScriptedJob2(
        [
            Job2Sentence(
                "Rent is stated in the dataset for this listing.", [f"dataset:{lid}:rent"]
            ),
            Job2Sentence("The area is very safe.", ["guide:made-up"]),
            Job2Sentence("Everyone loves it here.", []),
        ]
    )

    await orch.handle_text(session, "why did you pick this one?")
    await session.speaking

    assert session.job2_bound == 1
    assert session.job2_drops == {
        "no_refs": 1,
        "unknown_ref": 1,
        "gap_assertion": 0,
        "unsupported": 0,
    }
