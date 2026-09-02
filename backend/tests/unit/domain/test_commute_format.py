from datetime import date

from scout.domain.commute_format import render_commute
from scout.domain.provenance import Distance, Method, Provenanced, Source, Timing


def osm(method, minutes=14, metres=1100):
    return Provenanced(
        value=Distance(metres=metres, minutes=minutes),
        source=Source.OSM,
        timing=Timing.PRECOMPUTED,
        method=method,
        as_of=date(2026, 9, 1),
    )


def test_osm_routed_all_three_layers_say_route():
    r = render_commute(osm(Method.ROUTED), what="Metro")
    assert "by route" in r.spoken
    assert r.badge == "by route"
    assert r.full_label == "[OSM routing — precomputed 2026-09-01]"
    assert r.value_text == "1.1 km"


def test_osm_straight_line_all_three_layers_say_straight_line():
    r = render_commute(osm(Method.STRAIGHT_LINE, minutes=None), what="Metro")
    assert "in a straight line" in r.spoken
    assert r.badge == "straight-line"
    assert r.full_label == "[OSM straight-line — precomputed 2026-09-01]"


def test_live_straight_line_carries_caveat_in_the_same_breath():
    f = Provenanced(
        value=Distance(metres=6000, minutes=None),
        source=Source.COMPUTED,
        timing=Timing.LIVE,
        method=Method.STRAIGHT_LINE,
    )
    r = render_commute(f, what="Work")
    assert "straight-line" in r.spoken and "road distance will be longer" in r.spoken
    assert r.badge == "straight-line"
    assert r.full_label == "[Straight-line from coordinates — computed now]"


def test_live_routed_label():
    f = Provenanced(
        value=Distance(metres=9000, minutes=32),
        source=Source.OSM,
        timing=Timing.LIVE,
        method=Method.ROUTED,
    )
    r = render_commute(f, what="Work")
    assert "by route" in r.spoken and r.full_label == "[OSM routing — live]"


def test_null_distance_reads_not_stated_never_zero():
    f = Provenanced[Distance | None](
        value=None, source=Source.OSM, timing=Timing.PRECOMPUTED, as_of=date(2026, 9, 1)
    )
    r = render_commute(f, what="Metro")
    assert r.value_text == "not stated" and r.badge == "" and "0" not in r.spoken


def test_sub_kilometre_distance_reads_in_metres_never_zero_point_zero():
    r = render_commute(osm(Method.ROUTED, minutes=1, metres=40), what="Metro")
    assert r.value_text == "40 m"
    assert "0.0" not in r.spoken and "0.0" not in r.value_text


def test_a_long_routed_distance_is_not_called_a_walk():
    r = render_commute(osm(Method.ROUTED, minutes=38, metres=5000), what="Hospital")
    assert "walk" not in r.spoken
    assert "by route" in r.spoken
    assert r.badge == "by route"
