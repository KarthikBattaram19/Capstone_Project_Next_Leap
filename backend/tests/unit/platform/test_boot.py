import pytest

from scout.config import Settings
from scout.platform.boot import BootError, check_secrets, run_boot_checks


def settings(**over):
    # Every field is passed explicitly: keyword arguments beat the env file, so a
    # developer's real backend/.env can never leak into a test run.
    base = {
        "deepgram_api_key": "d",
        "groq_api_key": "g",
        "anthropic_api_key": "a",
        "smallest_api_key": "s",
        "google_oauth_credentials": '{"client_id":"x","client_secret":"y","refresh_token":"z"}',
        "google_tenant_calendar_id": "t",
        "google_owner_calendar_id": "o",
        "google_sender_email": "e@x",
        "operator_token": "op",
        "bundle_dir": "../data/bundle",
        "cors_allowed_origins": "http://localhost:3000",
    }
    base.update(over)
    return Settings(**base)


def test_missing_secret_fails_boot_and_names_it():
    with pytest.raises(BootError) as e:
        run_boot_checks(settings(groq_api_key=""), [check_secrets])
    assert "GROQ_API_KEY" in str(e.value)


def test_all_failures_are_reported_at_once():
    # An operator missing two things is told both at once, not one per restart.
    def always_fails(_):
        raise BootError("dataset did not load")

    with pytest.raises(BootError) as e:
        run_boot_checks(settings(groq_api_key=""), [check_secrets, always_fails])
    assert "GROQ_API_KEY" in str(e.value)
    assert "dataset did not load" in str(e.value)


def test_cors_is_never_wildcard():
    with pytest.raises(BootError):
        run_boot_checks(settings(cors_allowed_origins="*"), [check_secrets])
