from scout.conversation.job2 import SentenceStreamParser


def test_yields_each_sentence_as_soon_as_it_closes():
    p = SentenceStreamParser()
    out = []
    for delta in (
        '{"sentences": [{"te',
        'xt": "Rent is ₹35,000.", "fact_refs": ["dataset:a:rent"]}',
        ', {"text": "Metro is 1.1 km by route.", "fact_refs": ["osm:a:nearest_metro"]}]',
        ', "gaps": ["safety"]}',
    ):
        out.extend(p.feed(delta))
    assert [s.text for s in out] == ["Rent is ₹35,000.", "Metro is 1.1 km by route."]
    assert out[1].fact_refs == ["osm:a:nearest_metro"]
    assert p.gaps() == ["safety"]


def test_nested_braces_and_escaped_quotes_inside_text():
    p = SentenceStreamParser()
    out = p.feed(
        '{"sentences":[{"text":"He said \\"quiet\\" {mostly}.","fact_refs":["guide:x-0-1"]}],'
        '"gaps":[]}'
    )
    assert out[0].text == 'He said "quiet" {mostly}.'
