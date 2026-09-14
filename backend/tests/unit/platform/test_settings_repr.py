"""A Settings repr never carries a secret — pytest prints fixture values under a failure."""

from scout.config import Settings

SECRETS = {
    "anthropic_api_key": "sk-ant-api03-REDACT-ME-0123456789",
    "gemini_api_key": "AIzaREDACT-ME-0123456789",
    "groq_api_key": "gsk_REDACT-ME",
    "deepgram_api_key": "dg-REDACT-ME",
    "smallest_api_key": "sm-REDACT-ME",
    "operator_token": "op-REDACT-ME",
    "google_oauth_credentials": '{"refresh_token": "1//REDACT-ME"}',
}


def test_repr_and_str_show_that_a_secret_is_set_but_never_its_value():
    s = Settings(_env_file=None, **SECRETS)
    for text in (repr(s), str(s)):
        for value in SECRETS.values():
            assert value not in text and "REDACT-ME" not in text
        assert "anthropic_api_key='<set>'" in text


def test_an_unset_secret_still_reads_as_empty():
    s = Settings(_env_file=None)
    assert "anthropic_api_key=''" in repr(s)


def test_the_values_themselves_are_untouched():
    s = Settings(_env_file=None, **SECRETS)
    assert s.anthropic_api_key == SECRETS["anthropic_api_key"]
    assert s.model_dump()["gemini_api_key"] == SECRETS["gemini_api_key"]
