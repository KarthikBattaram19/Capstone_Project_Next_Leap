import pytest

from scout.conversation.hold import looks_unfinished


@pytest.mark.parametrize(
    "text",
    [
        "two BHK under",
        "close to",
        "budget forty",
        "around 35",
        "one point two",
        "in Koramangala and",
        "rent about",
    ],
)
def test_holds_on_continuation_or_bare_number(text):
    assert looks_unfinished(text)


@pytest.mark.parametrize(
    "text",
    [
        "two BHK under forty thousand",
        "budget 35k",
        "parking needed",
        "1.2 lakh deposit",
        "Koramangala",
    ],
)
def test_finishes_on_complete_phrases(text):
    assert not looks_unfinished(text)
