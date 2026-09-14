"""Job 1 against the real Groq model. Skipped unless GROQ_API_KEY is present.

Run with a populated backend/.env:  python -m pytest backend/tests/integration -q
CI never runs these — its pytest target is backend/tests/unit.
"""

import pytest

from scout.config import ENV_FILE, Settings
from scout.conversation.job1 import Job1
from scout.domain.constraints import ConstraintSet
from scout.providers import make_job1_client

_S = Settings()
_KEY_ENV = "GEMINI_API_KEY" if _S.job1_provider == "gemini" else "GROQ_API_KEY"
_KEY = _S.gemini_api_key if _S.job1_provider == "gemini" else _S.groq_api_key
pytestmark = pytest.mark.skipif(
    not _KEY,
    reason=f"{_KEY_ENV} not set (looked in the environment and {ENV_FILE})",
)

LOCALITIES = ["Koramangala", "HSR Layout"]


def _job1() -> Job1:
    return Job1(make_job1_client(Settings()), LOCALITIES)


async def test_a_full_preference_sentence_extracts_and_normalises():
    res = await _job1().extract("2BHK in Koramangala budget 35k need car parking", ConstraintSet())
    assert res.intent in ("set_preferences", "refine")
    rent = next(e for e in res.edits if e.field == "rent_max")
    assert rent.value == 35000, f"amount not normalised at this layer: {rent.value!r}"
    assert any(e.field == "localities" and e.value == "Koramangala" for e in res.edits)


async def test_a_refinement_edits_only_the_budget():
    current = ConstraintSet(localities=("Koramangala",), rent_max=45000)
    res = await _job1().extract("drop anything above 40k", current)
    rent = next(e for e in res.edits if e.field == "rent_max")
    assert rent.value == 40000
    assert not any(e.field == "localities" for e in res.edits), "restated an unchanged requirement"


async def test_a_yes_to_the_readback_is_a_confirmation():
    current = ConstraintSet(localities=("Koramangala",), rent_max=40000)
    res = await _job1().extract("yes that's right", current)
    assert res.intent == "confirm_yes"


async def test_bhk_alone_never_becomes_a_property_type():
    # "one BHK in Whitefield under fifteen thousand" once came back with property_type
    # "apartment", which excluded the only Whitefield 1BHK in the eval slice — a villa
    # (Suite C, c-020, 2026-09-10). A bedroom count is not a property type.
    res = await Job1(make_job1_client(Settings()), ["Whitefield"]).extract(
        "one BHK in Whitefield under fifteen thousand", ConstraintSet()
    )
    fields = {e.field for e in res.edits}
    assert "property_type" not in fields, fields
    assert {"localities", "bhk_type", "rent_max"} <= fields, fields


async def test_i_work_in_is_a_commute_point_not_a_locality():
    # "I work in Whitefield" once came back as a locality edit, which emptied an HSR Layout
    # shortlist and turned "why the first one?" into "Which one do you mean?" (Suite C,
    # c-013, 2026-09-15). Where the renter travels TO is the commute field, nothing else.
    current = ConstraintSet(localities=("HSR Layout",), rent_max=35000, bhk_type="2BHK")
    res = await Job1(make_job1_client(Settings()), LOCALITIES + ["Whitefield"]).extract(
        "I work in Whitefield", current
    )
    fields = {e.field: e for e in res.edits}
    assert "commute" in fields, res.edits
    assert "Whitefield" in str(fields["commute"].value), res.edits
    assert "localities" not in fields, res.edits
