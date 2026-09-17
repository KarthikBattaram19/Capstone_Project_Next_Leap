import inspect

from scout.conversation import persona
from scout.conversation.job1 import JOB1_SCHEMA
from scout.conversation.speaker import split_sentences


def test_greeting_fits_the_opening_budget():
    assert len(split_sentences(persona.GREETING)) <= 3
    assert len(persona.GREETING.split()) <= 150


def test_greeting_introduces_the_agent_and_asks_for_preferences():
    assert persona.NAME in persona.GREETING
    assert "For example" in persona.GREETING


def test_greeting_is_a_constant_not_a_call():
    # P8's reason (arch §11.2): the opening line can never become a model call.
    assert isinstance(persona.GREETING, str)
    assert "providers" not in inspect.getsource(persona)


def test_every_conversational_reply_fits_the_sentence_cap():
    # What makes arch §11.2's "at most 3 sentences" a rule rather than an aspiration. The
    # shortlist reading and the Type B explanation are deliberately not in this dict: their
    # length is set by the facts that resolved, not by the persona.
    from scout.conversation.orchestrator import CONVERSATIONAL_REPLIES

    # The lines added by the 2026-09-17 voice fix batch (A1, A4, A5) are in the dict, so the
    # cap covers them.
    assert {"unclear", "feedback", "goodbye"} <= set(CONVERSATIONAL_REPLIES)
    for name, text in CONVERSATIONAL_REPLIES.items():
        assert len(split_sentences(text)) <= persona.MAX_REPLY_SENTENCES, name


def test_job1_schema_has_no_slot_for_personal_data():
    # Where the privacy rule is actually enforced: extraction has no field to put a phone
    # number in, so wording is not the only thing standing between the renter and an
    # unwanted question.
    assert set(JOB1_SCHEMA["properties"]) & persona.FORBIDDEN_PII_FIELDS == set()
    assert "email" in JOB1_SCHEMA["properties"]
