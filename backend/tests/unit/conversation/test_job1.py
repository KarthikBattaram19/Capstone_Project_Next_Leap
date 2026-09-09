import pytest

from scout.conversation.job1 import JOB1_SCHEMA, Job1, Job1Down
from scout.domain.constraints import ConstraintSet


class FakeGroq:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def complete_json(self, system, user, schema_name, schema):
        self.calls.append(user)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


GOOD = {
    "intent": "set_preferences",
    "edits": [
        {"field": "bhk_type", "op": "set", "value": "2BHK"},
        {"field": "localities", "op": "add", "value": "Koramangala"},
        {"field": "rent_max", "op": "set", "value": "35k"},
        {"field": "parking_required", "op": "set", "value": "four_wheeler"},
    ],
    "ambiguities": [],
    "reference": None,
    "email": None,
    "code": None,
    "slot_choice": None,
}


def test_schema_is_strict():
    assert JOB1_SCHEMA["additionalProperties"] is False
    assert set(JOB1_SCHEMA["required"]) == set(JOB1_SCHEMA["properties"])


async def test_amounts_are_normalised_at_the_extraction_layer():
    j = Job1(FakeGroq([GOOD]), localities=["Koramangala", "HSR Layout"])
    res = await j.extract("2BHK in Koramangala budget 35k need car parking", ConstraintSet())
    rent = next(e for e in res.edits if e.field == "rent_max")
    assert rent.value == 35000


async def test_unknown_locality_becomes_a_question_not_a_substitution():
    bad = dict(GOOD, edits=[{"field": "localities", "op": "add", "value": "Whitefield"}])
    res = await Job1(FakeGroq([bad]), localities=["Koramangala", "HSR Layout"]).extract(
        "2BHK in Whitefield", ConstraintSet()
    )
    assert not any(e.field == "localities" for e in res.edits)
    assert res.ambiguities
    assert res.ambiguities[0].field == "locality"
    assert "Whitefield" in res.ambiguities[0].question


async def test_schema_violation_retries_once_then_is_down():
    j = Job1(FakeGroq([{"intent": "set_preferences"}, {"nonsense": 1}]), localities=["Koramangala"])
    with pytest.raises(Job1Down):
        await j.extract("hello", ConstraintSet())
    assert len(j.client.calls) == 2


async def test_bare_number_is_reported_ambiguous():
    bad = dict(GOOD, edits=[{"field": "rent_max", "op": "set", "value": "thirty five"}])
    res = await Job1(FakeGroq([bad]), localities=["Koramangala"]).extract(
        "budget thirty five", ConstraintSet()
    )
    assert not any(e.field == "rent_max" for e in res.edits)
    assert any(a.field == "rent_max" and "35,000" in a.question for a in res.ambiguities)
