import pytest
from pydantic import ValidationError

from scout.contract.export import export_schema
from scout.contract.messages import StopIn


def test_stop_is_an_inbound_message_in_the_contract():
    assert StopIn.model_validate({"type": "stop"}).type == "stop"
    with pytest.raises(ValidationError):
        StopIn.model_validate({"type": "stop", "text": "no"})
    assert "StopIn" in export_schema()["$defs"]
