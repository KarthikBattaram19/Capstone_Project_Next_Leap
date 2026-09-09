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


def test_job1_schema_has_no_slot_for_personal_data():
    # Where the privacy rule is actually enforced: extraction has no field to put a phone
    # number in, so wording is not the only thing standing between the renter and an
    # unwanted question.
    assert set(JOB1_SCHEMA["properties"]) & persona.FORBIDDEN_PII_FIELDS == set()
    assert "email" in JOB1_SCHEMA["properties"]
