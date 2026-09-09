import pytest

from scout.engines.amounts import Ambiguous, Amount, NoAmount, normalise_amount


@pytest.mark.parametrize(
    "text,rupees",
    [
        ("budget 35k", 35000),
        ("under 35,000", 35000),
        ("thirty five thousand", 35000),
        ("thirty-five thousand", 35000),
        ("1.2 lakh", 120000),
        ("one point two lakhs deposit", 120000),
        ("forty thousand", 40000),
        ("2 lakh", 200000),
        ("Rs 28000", 28000),
        # The spoken tens whose first syllable is also a smaller number word.
        ("sixty thousand", 60000),
        ("ninety thousand", 90000),
    ],
)
def test_unambiguous_amounts(text, rupees):
    r = normalise_amount(text)
    assert isinstance(r, Amount) and r.rupees == rupees


@pytest.mark.parametrize(
    # A bare magnitude is never assumed. The candidate the renter is most likely to have
    # meant differs per form: "thirty five"/"35" could be ₹35,000; "3.5" could not — it
    # reads as 3.5 thousand or 3.5 lakh. Either way the assistant asks.
    "text,expected_candidate",
    [
        ("thirty five", 35000),
        ("3.5", 350000),
        ("budget 35", 35000),
    ],
)
def test_bare_magnitude_is_ambiguous_not_assumed(text, expected_candidate):
    r = normalise_amount(text)
    assert isinstance(r, Ambiguous) and expected_candidate in r.candidates


def test_no_amount():
    assert isinstance(normalise_amount("two BHK in Koramangala"), NoAmount)
