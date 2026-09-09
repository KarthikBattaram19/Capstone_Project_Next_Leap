from scout.domain.provenance import Source
from scout.grounding.retrieval import Retrieval
from scout.platform.artefacts import ArtefactStore


def test_only_the_named_localitys_chunks_can_come_back(bundle_min):
    store = ArtefactStore.load(bundle_min)
    hits = Retrieval(store).retrieve("HSR Layout", "what is Koramangala like?", k=4)
    assert hits
    for h in hits:
        assert h.value.locality == "HSR Layout"
        assert h.source is Source.GUIDE
        assert h.citation_ref.startswith("guide:")


def test_unknown_locality_is_empty_not_an_error(bundle_min):
    assert Retrieval(ArtefactStore.load(bundle_min)).retrieve("Nowhere", "anything") == []
