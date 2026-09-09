"""Job 2 against the real Anthropic model. Skipped unless ANTHROPIC_API_KEY is present.

Run with a populated backend/.env:  python -m pytest backend/tests/integration -q
CI never runs these — its pytest target is backend/tests/unit.
"""

import pytest

from scout.config import ENV_FILE, Settings
from scout.conversation.job2 import Job2
from scout.engines.commute import CommuteService
from scout.grounding.assembler import ClaimAssembler
from scout.grounding.resolvers import ResolverRegistry
from scout.grounding.retrieval import Retrieval
from scout.platform.artefacts import ArtefactStore
from scout.providers.anthropic_job2 import AnthropicJob2Client

_S = Settings()
pytestmark = pytest.mark.skipif(
    not _S.anthropic_api_key,
    reason=f"ANTHROPIC_API_KEY not set (looked in the environment and {ENV_FILE})",
)


async def test_a_real_explanation_binds_and_cites_nothing_outside_the_bundle(bundle_min):
    store = ArtefactStore.load(bundle_min)
    registry = ResolverRegistry(store, CommuteService(store), Retrieval(store))
    lid = next(x for x in store.listings if store.listings[x].locality == "Koramangala")
    b = registry.resolve(lid, "what is this area like, and how far is the metro?", None)

    job2 = Job2(AnthropicJob2Client(Settings()))
    sentences = [s async for s in job2.explain(b, "what is this area like?")]
    assert sentences, "Job 2 produced no sentences"

    known = b.all_refs()
    for s in sentences:
        for ref in s.fact_refs:
            assert ref in known, f"cited a ref outside the bundle: {ref}"

    assembler = ClaimAssembler(b)
    bound = [c for c in (assembler.bind(s) for s in sentences) if c is not None]
    assert bound, f"nothing bound; sentences were {[s.text for s in sentences]}"
