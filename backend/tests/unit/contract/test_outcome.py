"""The five outcome shapes are distinct types; a wrong or missing `kind` is rejected."""

import pytest
from pydantic import TypeAdapter, ValidationError

from scout.contract.outcome import Empty, Failed, TurnOutcome

ta = TypeAdapter(TurnOutcome)


def test_empty_and_failed_are_different_shapes():
    e = ta.validate_python(
        {
            "kind": "empty",
            "unmet": [{"field": "rent_max", "value": "25000", "binding": True}],
            "suggestions": ["try 30k"],
            "spoken": "Nothing under 25k in Koramangala.",
        }
    )
    f = ta.validate_python(
        {
            "kind": "failed",
            "capability": "understanding",
            "tell_renter": "I didn't catch that, one moment",
            "retry_worth_it": True,
            "spoken": "I didn't catch that.",
        }
    )
    assert isinstance(e, Empty) and isinstance(f, Failed)
    assert type(e) is not type(f)


def test_failed_must_name_a_capability():
    with pytest.raises(ValidationError):
        ta.validate_python(
            {"kind": "failed", "tell_renter": "x", "retry_worth_it": False, "spoken": "x"}
        )


def test_unknown_kind_is_rejected():
    with pytest.raises(ValidationError):
        ta.validate_python({"kind": "error", "spoken": "x"})
