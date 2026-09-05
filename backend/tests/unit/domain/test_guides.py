from datetime import date

from scout.domain.guides import GuideChunk


def test_chunk_round_trips_with_its_locality_and_link():
    c = GuideChunk(
        id="koramangala-0-3",
        locality="Koramangala",
        title="Koramangala",
        url="https://en.wikipedia.org/wiki/Koramangala",
        text="A neighbourhood in south Bengaluru.",
        position=3,
        fetched_on=date(2026, 9, 2),
    )
    again = GuideChunk.model_validate_json(c.model_dump_json())
    assert again == c and again.locality == "Koramangala"
