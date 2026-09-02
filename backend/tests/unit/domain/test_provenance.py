from datetime import date

import pytest

from scout.domain.provenance import (
    Distance,
    Method,
    Provenanced,
    ProvenanceError,
    Source,
    Timing,
)


def test_distance_without_method_is_unrepresentable():
    with pytest.raises(ProvenanceError):
        Provenanced(
            value=Distance(metres=1100, minutes=14),
            source=Source.OSM,
            timing=Timing.PRECOMPUTED,
            method=None,
        )


def test_distance_with_method_is_fine():
    f = Provenanced(
        value=Distance(metres=1100, minutes=14),
        source=Source.OSM,
        timing=Timing.PRECOMPUTED,
        method=Method.ROUTED,
        as_of=date(2026, 9, 1),
    )
    assert f.value.metres == 1100 and f.method is Method.ROUTED


def test_null_is_a_real_value():
    f = Provenanced[int | None](value=None, source=Source.DATASET, timing=Timing.PRECOMPUTED)
    assert f.value is None and f.source is Source.DATASET


def test_none_source_carries_no_value():
    with pytest.raises(ProvenanceError):
        Provenanced(value=42, source=Source.NONE, timing=Timing.LIVE)


def test_wrapper_is_immutable():
    f = Provenanced(value=1, source=Source.DATASET, timing=Timing.PRECOMPUTED)
    with pytest.raises(Exception):  # noqa: B017 -- addendum specifies Exception
        f.value = 2  # type: ignore[misc]
