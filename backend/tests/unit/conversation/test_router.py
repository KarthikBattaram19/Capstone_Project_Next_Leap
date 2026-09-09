import pytest

from scout.conversation.router import classify_turn, parse_ordinal


@pytest.mark.parametrize(
    "text",
    [
        "why did you pick this one",
        "what's the area actually like",
        "is the commute realistic",
        "why this one?",
        "tell me about the neighbourhood",
        "is it safe at night",
        "how far is the metro from the second one",
    ],
)
def test_explanations_are_type_b_when_there_is_a_shortlist(text):
    assert classify_turn(text, has_shortlist=True) == "B"


@pytest.mark.parametrize(
    "text",
    [
        "two BHK in Koramangala under forty thousand",
        "drop anything above 40k",
        "book the second one Tuesday at four",
        "cancel my visit",
        "only metro adjacent",
    ],
)
def test_preferences_edits_and_bookings_are_type_a(text):
    assert classify_turn(text, has_shortlist=True) == "A"


def test_why_without_a_shortlist_is_type_a():
    assert classify_turn("why?", has_shortlist=False) == "A"


def test_parse_ordinal_reads_the_spoken_forms():
    assert parse_ordinal("how far is the metro from the second one") == 2
    assert parse_ordinal("why the first one?") == 1
    assert parse_ordinal("tell me about the area") is None
