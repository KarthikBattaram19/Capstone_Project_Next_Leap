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


@pytest.mark.parametrize(
    "text",
    [
        # Every one of these lost its explanation in the 2026-09-10 eval pass: the router
        # sent it to lane A, so Suite C's grounding assertions were skipped, not passed.
        "what is it like living around the first one?",
        "is there a park near the first one?",
        "when can I move into the first one?",
        "the guide says something about the deposit - what does it say?",
    ],
)
def test_a_question_about_a_named_listing_is_type_b(text):
    assert classify_turn(text, has_shortlist=True) == "B"


@pytest.mark.parametrize(
    "text",
    [
        # A listing reference does not make a turn an explanation. These act on the
        # shortlist or the booking and must stay in lane A, which never calls Job 2.
        "can I book the second one?",
        "book the second one",
        "drop the second one",
        "remove the second one from the list",
        "cancel the visit for the first one",
        # A preference that happens to read like a question is still a preference.
        "is there a 2BHK near Koramangala under 30,000",
        "only show me the ones near a park",
    ],
)
def test_acting_on_a_listing_stays_type_a(text):
    assert classify_turn(text, has_shortlist=True) == "A"


@pytest.mark.parametrize(
    "text",
    [
        # The action-verb guard exists for the new listing-reference patterns. It must not
        # take away an explanation the old router already routed correctly.
        "show me why you picked this one",
        "tell me about the neighbourhood around the second one",
    ],
)
def test_an_action_verb_inside_an_explanation_question_stays_type_b(text):
    assert classify_turn(text, has_shortlist=True) == "B"


@pytest.mark.parametrize(
    ("heard", "meant"),
    [
        # Deepgram's numerals/smart_format write spoken ordinals as digits (production,
        # 2026-09-17): "the first one" arrived as "The 1st 1." and was taken for another
        # language, and "book a visit for the 1st 1" was asked "which listing?".
        ("The 1st 1.", "The first one."),
        ("Book a visit for the 1st 1.", "Book a visit for the first one."),
        ("why the 2nd 1?", "why the second one?"),
        ("the 3rd one please", "the third one please"),
        ("under 40,000 rupees", "under 40,000 rupees"),
        ("a 1BHK on the 1st floor", "a 1BHK on the 1st floor"),
    ],
)
def test_digit_ordinals_are_read_as_the_words_the_renter_said(heard, meant):
    from scout.conversation.router import normalise_ordinals

    assert normalise_ordinals(heard) == meant
    assert parse_ordinal(normalise_ordinals("why the 2nd 1?")) == 2


@pytest.mark.parametrize(
    "text",
    [
        # A2, heard on production (2026-09-17) after a shortlist was on screen. Each one was
        # routed to lane A, where "Does it have a nearby hospital?" became a "with hospital"
        # requirement and an empty result, and "this 2nd listing" became a selection.
        "Does it have a nearby hospital?",
        "Enough. So does this have a lift facility?",
        "So what is so special about this 2nd listing?",
        "does this listing have a balcony",
        "does the flat have power backup?",
        "is there a hospital nearby?",
        "Is there a school near it?",
        "what is the rent of the second listing?",
        "how old is that property?",
        "is the third flat furnished?",
    ],
)
def test_a_question_about_it_or_this_listing_is_type_b(text):
    assert classify_turn(text, has_shortlist=True) == "B"


@pytest.mark.parametrize(
    "text",
    [
        # Acting still wins over the widened listing patterns.
        "show me ones with a lift",
        "show me the ones that have parking",
        "book the 2nd listing",
        "remove this property",
        # A requirement is still a requirement.
        "is there a 3BHK nearby under 40,000",
    ],
)
def test_acting_or_a_requirement_is_still_type_a(text):
    assert classify_turn(text, has_shortlist=True) == "A"


def test_a_sentence_full_of_requirements_is_not_a_why_question():
    """A3, heard on production (2026-09-17): the leading "why" sent it to lane B, which
    explained listing 1 and left the 1,856-listing shortlist unchanged."""
    heard = (
        "I don't know why you did not listen to me when I asked you to stop. Anyways, here "
        "I'm giving you a further filtering options. The size should be at least 1,500 "
        "square feet. It should be fully furnished. 3 BHK or more. Should be having a "
        "parking facility. And it should have lift facility."
    )
    assert classify_turn(heard, has_shortlist=True) == "A"


@pytest.mark.parametrize(
    "text",
    [
        # Requirement words inside a question are still the question.
        "why is the rent so high for the first one?",
        "why doesn't it have parking?",
        "why is this one not furnished",
    ],
)
def test_a_why_question_that_mentions_a_requirement_word_stays_type_b(text):
    assert classify_turn(text, has_shortlist=True) == "B"


@pytest.mark.parametrize(
    ("text", "n"),
    [
        ("So what is so special about this 2nd listing?", 2),
        ("what is the rent of the second listing?", 2),
        ("is the third flat furnished?", 3),
        ("tell me about the 1st property", 1),
        ("Does it have a nearby hospital?", None),
        ("does this listing have a lift", None),
        ("is there a park in this place", None),
    ],
)
def test_parse_ordinal_reads_an_ordinal_listing(text, n):
    assert parse_ordinal(text) == n
