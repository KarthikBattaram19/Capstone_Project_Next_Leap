import pytest

from scout.domain.provenance import Source
from scout.engines.commute import CommuteService
from scout.grounding.resolvers import ResolverRegistry
from scout.grounding.retrieval import Retrieval
from scout.platform.artefacts import ArtefactStore


@pytest.fixture
def registry(bundle_min):
    s = ArtefactStore.load(bundle_min)
    return s, ResolverRegistry(s, CommuteService(s), Retrieval(s))


def test_bundle_holds_only_wrapped_facts_from_the_right_listing(registry):
    store, reg = registry
    lid = next(iter(store.listings))
    b = reg.resolve(lid, "is it noisy?", commute_point=None)
    assert b.listing_id == lid
    assert b.locality == store.listings[lid].locality
    assert all(hasattr(f, "source") for f in b.facts.values())
    assert f"dataset:{lid}" in b.facts[f"dataset:{lid}:rent"].citation_ref
    assert any(k.startswith("osm:") for k in b.facts)


def test_null_facts_are_declared_gaps(registry):
    store, reg = registry
    lid = next(x for x in store.listings if store.listings[x].field("deposit").value is None)
    b = reg.resolve(lid, "deposit?", None)
    assert f"dataset:{lid}:deposit" in b.gaps()


def test_other_claims_resolve_to_none(registry):
    _, reg = registry
    f = reg.resolve_kind("other")
    assert f.value is None and f.source is Source.NONE
