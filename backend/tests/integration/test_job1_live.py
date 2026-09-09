"""Job 1 against the real Groq model. Skipped unless GROQ_API_KEY is present.

Run with a populated backend/.env:  python -m pytest backend/tests/integration -q
CI never runs these — its pytest target is backend/tests/unit.
"""

import pytest

from scout.config import ENV_FILE, Settings
from scout.conversation.job1 import Job1
from scout.domain.constraints import ConstraintSet
from scout.providers.groq_job1 import GroqJob1Client

_S = Settings()
pytestmark = pytest.mark.skipif(
    not _S.groq_api_key,
    reason=f"GROQ_API_KEY not set (looked in the environment and {ENV_FILE})",
)

LOCALITIES = ["Koramangala", "HSR Layout"]


def _job1() -> Job1:
    return Job1(GroqJob1Client(Settings()), LOCALITIES)


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
