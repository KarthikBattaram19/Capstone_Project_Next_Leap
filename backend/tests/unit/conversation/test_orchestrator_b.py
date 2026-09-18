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


async def test_resolving_facts_does_not_stall_the_event_loop(make, monkeypatch):
    """Retrieval embeds the question on the CPU. Run on the event loop it froze every other
    session and this one's own audio for its whole duration - 2.7 s on production
    (2026-09-17). It runs in a worker thread, so the loop keeps ticking."""
    import asyncio
    import time

    from scout.grounding.retrieval import Retrieval

    def slow(self, locality, question, k=4):
        time.sleep(0.3)
        return []

    monkeypatch.setattr(Retrieval, "retrieve", slow)
    orch, session, _, _ = make(ScriptedJob2([]))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    t = asyncio.create_task(ticker())
    await orch.handle_text(session, "why did you pick this one?")
    t.cancel()
    assert ticks >= 8, f"the loop only ticked {ticks} times during a 0.3 s resolve"


class RecordingJob2(ScriptedJob2):
    """Says what the scripted sentences say and keeps the facts it was handed."""

    def __init__(self, make_sentences):
        super().__init__([])
        self.make_sentences = make_sentences
        self.bundles: list = []

    async def explain(self, bundle, question):
        self.bundles.append(bundle)
        for s in self.make_sentences(bundle.listing_id):
            yield s


async def test_does_it_have_a_nearby_hospital_is_answered_about_the_listing_in_focus(make):
    """A2, heard on production (2026-09-17) with a shortlist on screen: "Does it have a nearby
    hospital?" went to Job 1, became a "with hospital" requirement and an empty result. It is a
    question about the listing last referred to, answered from its facts."""
    from scout.domain.shortlist import Shortlist, ShortlistEntry

    job2 = RecordingJob2(
        lambda lid: [
            Job2Sentence(
                "The nearest hospital is about 600 m away.", [f"osm:{lid}:nearest_hospital"]
            )
        ]
    )
    orch, session, speaker, _ = make(job2)  # no Job 1 answers scripted: Job 1 must not run
    session.last_read_order = ["kor-001", "kor-002"]
    session.shortlist = Shortlist(
        matched=(ShortlistEntry("kor-001", 1), ShortlistEntry("kor-002", 2))
    )
    session.focus_listing_id = "kor-001"

    out = await orch.handle_text(session, "Does it have a nearby hospital?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    assert out.view_model.explanation.listing_id == "kor-001"
    hospital = job2.bundles[0].facts["osm:kor-001:nearest_hospital"]
    assert hospital.value.metres == 600
    assert "600 m" in out.spoken
    assert "The nearest hospital is about 600 m away." in speaker.said


async def test_this_2nd_listing_is_explained_not_selected(make):
    """A2: "So what is so special about this 2nd listing?" was read back as a selection."""
    from scout.domain.shortlist import Shortlist, ShortlistEntry

    job2 = RecordingJob2(lambda lid: [])
    orch, session, _speaker, _ = make(job2)
    session.last_read_order = ["kor-001", "kor-002"]
    session.shortlist = Shortlist(
        matched=(ShortlistEntry("kor-001", 1), ShortlistEntry("kor-002", 2))
    )

    out = await orch.handle_text(session, "So what is so special about this 2nd listing?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    assert out.view_model.explanation.listing_id == "kor-002"
    assert session.focus_listing_id == "kor-002"


class GappyJob2(RecordingJob2):
    """What Job 2 did on production (2026-09-17, conv 4): an unformatted rent, gap sentences,
    the same gap twice, and raw field names in its gaps list."""

    def __init__(self):
        super().__init__(
            lambda lid: [
                Job2Sentence(
                    "The rent is 42000 a month.",
                    [f"dataset:{lid}:rent"],
                ),
                Job2Sentence("It is a 2BHK.", [f"dataset:{lid}:bhk_type"]),
                Job2Sentence(
                    "I don't have a maintenance figure for this listing.",
                    [f"dataset:{lid}:maintenance_charges"],
                ),
                Job2Sentence(
                    "I don't have a maintenance figure for this listing.",
                    [f"dataset:{lid}:maintenance_included"],
                ),
                Job2Sentence("It is in the Sobha Iris society.", [f"dataset:{lid}:society_name"]),
                Job2Sentence("The building has 6 floors.", [f"dataset:{lid}:total_floors"]),
                Job2Sentence("It has 2 bathrooms.", [f"dataset:{lid}:bathrooms"]),
            ]
        )

    async def explain(self, bundle, question):
        async for s in super().explain(bundle, question):
            yield s
        self.last_gaps = [
            "maintenance_charges",
            "maintenance_included",
            "lift",
            "floor",
            "available_from",
            "amenities",
            "area_basis",
            "restaurants_within_500m",
        ]


async def test_why_the_first_one_is_a_short_answer_with_no_field_names(make):
    """E1, conv 4 on production (2026-09-17): "why the first one?" was a 57 s monologue that
    read every gap aloud, twice for maintenance, with raw field names and "30000"."""
    from scout.conversation.speaker import split_sentences

    job2 = GappyJob2()
    orch, session, speaker, _ = make(job2)
    session.last_read_order = ["kor-001"]

    out = await orch.handle_text(session, "why the first one?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    exp = out.view_model.explanation
    spoken_after_opener = out.spoken[len(exp.opener) :].strip()
    assert len(split_sentences(spoken_after_opener)) <= 3, out.spoken
    assert len(split_sentences(out.spoken)) <= 4, out.spoken
    assert "_" not in out.spoken, out.spoken
    assert all("_" not in s for s in speaker.said), speaker.said
    assert " ".join(speaker.said) == out.spoken
    assert "42000" not in out.spoken and "₹42,000" in out.spoken, out.spoken
    assert any("₹42,000" in c.text for c in exp.claims), [c.text for c in exp.claims]
    assert all("42000" not in c.text for c in exp.claims), [c.text for c in exp.claims]
    assert out.spoken.count("maintenance") <= 1, out.spoken
    assert out.spoken.count("don't have") == 1, out.spoken
    # The gaps are on screen: every one, once, in words.
    assert all("_" not in g for g in exp.gaps), exp.gaps
    assert len(exp.gaps) == len({g.lower() for g in exp.gaps}), exp.gaps
    assert sum("maintenance" in g for g in exp.gaps) == 1, exp.gaps
    assert any("lift" in g for g in exp.gaps), exp.gaps
    assert any("restaurants" in g for g in exp.gaps), exp.gaps


class NeighbourhoodJob2(RecordingJob2):
    """A listing claim, optionally a guide claim, and gaps: what production answered with."""

    def __init__(self, with_guide: bool):
        def sentences(lid):
            out = [Job2Sentence("It has 2 bathrooms.", [f"dataset:{lid}:bathrooms"])]
            if with_guide:
                out.append(
                    Job2Sentence(
                        "The guide describes the blocks near Forum Mall as the noisiest at night.",
                        ["guide:koramangala-0-1"],
                    )
                )
            return out

        super().__init__(sentences)

    async def explain(self, bundle, question):
        async for s in super().explain(bundle, question):
            yield s
        self.last_gaps = ["maintenance_charges", "parking"]


def _dangling(spoken: str) -> list[str]:
    from scout.conversation.speaker import split_sentences

    return [s for s in split_sentences(spoken) if s.rstrip().endswith("—")]


async def test_no_neighbourhood_heading_when_no_neighbourhood_claim_follows(make):
    """E1 replay on production (2026-09-17, after 3c69bbf): "It's ₹33,000 a month for a 2BHK,
    about 4.0 km by route to the metro. On the neighbourhood — I don't have some details for
    this listing, like the maintenance and parking." The heading led into the gap line."""
    job2 = NeighbourhoodJob2(with_guide=False)
    orch, session, speaker, _ = make(job2)

    out = await orch.handle_text(session, "why did you pick this one?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    assert job2.bundles[0].chunks, "the fixture must have guide passages for this to test"
    assert "On the neighbourhood" not in out.spoken, out.spoken
    assert not _dangling(out.spoken), out.spoken
    assert all(not s.rstrip().endswith("—") for s in speaker.said), speaker.said
    assert "On the neighbourhood" not in out.view_model.explanation.opener
    assert "I don't have" in out.spoken
    assert " ".join(speaker.said) == out.spoken


async def test_the_neighbourhood_heading_leads_into_a_neighbourhood_claim(make):
    job2 = NeighbourhoodJob2(with_guide=True)
    orch, session, speaker, _ = make(job2)

    out = await orch.handle_text(session, "why did you pick this one?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    assert (
        "On the neighbourhood — The guide describes the blocks near Forum Mall" in out.spoken
        or "On the neighbourhood — the guide describes the blocks near Forum Mall" in out.spoken
    ), out.spoken
    assert out.spoken.count("On the neighbourhood") == 1, out.spoken
    assert not _dangling(out.spoken), out.spoken
    assert "_" not in out.spoken
    assert " ".join(speaker.said) == out.spoken
    # On screen the claim is shown as Job 2 wrote it.
    texts = [c.text for c in out.view_model.explanation.claims]
    assert any(t.startswith("The guide describes") for t in texts), texts


async def test_job2_down_leaves_no_dangling_heading(make):
    orch, session, speaker, _lid = make(ScriptedJob2([], raises=Job2Down("provider down")))
    out = await orch.handle_text(session, "why did you pick this one?")
    await session.speaking
    assert isinstance(out, Degraded)
    assert "On the neighbourhood" not in out.spoken, out.spoken
    assert not _dangling(" ".join(speaker.said)), speaker.said


async def test_when_nothing_binds_she_says_so_and_offers_what_she_can_do(make):
    """Production 2026-09-18: `job2 assembler: 0 bound, 1 dropped (no_refs=1)`.

    With nothing bound the renter heard the code-built opener and no answer at all. She
    now says she could not answer it and what she can still do — no invented fact.
    """
    orch, session, speaker, _lid = make(ScriptedJob2([]))
    orch.job2 = ScriptedJob2([Job2Sentence("It's a lovely place to live.", [])])

    out = await orch.handle_text(session, "why did you pick this one?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    exp = out.view_model.explanation
    assert exp is not None and exp.claims == []
    said = " ".join(speaker.said)
    assert said.startswith(exp.opener), said
    rest = said[len(exp.opener) :].strip()
    assert "couldn't answer" in rest, f"nothing beyond the opener answered it: {speaker.said}"
    assert "_" not in rest, rest  # E1: never a raw field name
    assert "On the neighbourhood —" not in said, said  # E1: no dangling heading
    assert rest in out.spoken, (rest, out.spoken)
    assert any("couldn't answer" in n for n in out.view_model.notices), out.view_model.notices
    assert said.count(".") <= 4, said  # E1: at most ~4 sentences


async def test_a_bound_claim_leaves_the_nothing_bound_line_unsaid(make):
    """The line is for the empty case only: one bound claim IS an answer."""
    orch, session, speaker, lid = make(ScriptedJob2([]))
    orch.job2 = ScriptedJob2(
        [Job2Sentence("The deposit is two months' rent.", [f"dataset:{lid}:rent"])]
    )

    out = await orch.handle_text(session, "why did you pick this one?")
    await session.speaking

    assert isinstance(out, Answered), f"got {out.kind}: {out.spoken}"
    assert "couldn't answer" not in " ".join(speaker.said), speaker.said
