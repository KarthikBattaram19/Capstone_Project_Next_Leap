from scout.pipeline.collect_guides import extract_text

PAGE = """
<html><head><title>Koramangala - Wikipedia</title></head><body>
<div id="mw-content-text">
<table class="infobox"><tr><td><p>Population 100000 in the infobox table, which is not prose at all.</p></td></tr></table>
<p>Koramangala is a neighbourhood of <a href="/wiki/Bengaluru">Bengaluru</a>, India.
It is a residential locality with wide, tree-lined boulevards and a mix of bungalows.<sup>[1]</sup>
<span class="plainlinks"><span class="geo-inline">12°56′N 77°37′E / 12.93°N 77.62°E</span></span></p>
<p>Too short.</p>
<p>The following are the direct buses that serve the locality from the city centre:</p>
<ul><li>500D</li><li>171</li></ul>
<p>Blocks 1 to 4 are separated from blocks 5 to 8 by the Inner Ring Road leading to
<a href="/wiki/Domlur">Domlur</a> and <a href="/wiki/Indiranagar">Indiranagar</a>. Up to the
1970s one would pass the village of Adugodi on the Hosur Road.</p>
</div>
<footer><p>This footer paragraph has more than eight words and must never be kept.</p></footer>
</body></html>
"""


def test_title_is_the_page_name_without_the_site_suffix():
    title, _ = extract_text(PAGE)
    assert title == "Koramangala"


def test_only_readable_body_paragraphs_survive():
    _, text = extract_text(PAGE)
    paras = text.split("\n\n")
    assert len(paras) == 2
    assert paras[0].startswith("Koramangala is a neighbourhood of Bengaluru, India.")
    assert paras[1].startswith("Blocks 1 to 4")
    assert "infobox" not in text
    assert "footer paragraph" not in text
    assert "Too short" not in text
    assert "direct buses" not in text  # a paragraph that only introduces a list


def test_citation_markers_coordinates_and_link_spacing_are_cleaned():
    _, text = extract_text(PAGE)
    assert "[1]" not in text
    assert "°" not in text
    assert "Bengaluru , India" not in text
    assert "Domlur and Indiranagar." in text
    assert "\n" not in text.split("\n\n")[0]
