from typing import ClassVar

from scout.engines.availability import AvailabilityRegister


class FakeStore:
    listing_records: ClassVar[dict] = {
        "a": type("R", (), {"availability_status": True})(),
        "b": type("R", (), {"availability_status": True})(),
    }


def test_overlay_shadows_dataset_and_dies_with_the_object():
    reg = AvailabilityRegister(FakeStore())
    assert reg.is_available("a")
    reg.set("a", False)
    assert not reg.is_available("a")
    assert reg.is_available("b")
    # A "restart" returns the import's value: the overlay dies with the process (AD-11).
    assert AvailabilityRegister(FakeStore()).is_available("a")
