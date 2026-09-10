from datetime import UTC, date, datetime, timedelta, timezone

from scout.engines.slots import IST, Slot, SlotService

NOW_UTC = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)  # 09:00 IST Tuesday


def test_window_is_ist_even_when_now_is_utc():
    s = SlotService()
    start, end = s.window(NOW_UTC)
    assert start.tzinfo is IST
    assert start.hour == 10
    assert start.date() == date(2026, 9, 1)
    assert (end - start).days == 7


def test_free_slots_are_hourly_10_to_18_and_skip_busy():
    s = SlotService()
    busy = [
        (
            datetime(2026, 9, 1, 11, 0, tzinfo=IST),
            datetime(2026, 9, 1, 12, 0, tzinfo=IST),
        )
    ]
    slots = s.free_slots(busy, NOW_UTC)
    first_day = [x for x in slots if x.start.date() == date(2026, 9, 1)]
    assert [x.start.hour for x in first_day] == [10, 12, 13, 14, 15, 16, 17]
    assert all(x.end - x.start == timedelta(hours=1) for x in slots)


def test_server_local_time_is_never_used(monkeypatch):
    # A server in US-West: naive "now" would be 8 pm the previous day. The service must not care.
    now_us = NOW_UTC.astimezone(timezone(timedelta(hours=-7)))
    assert SlotService().window(now_us) == SlotService().window(NOW_UTC)


def test_has_started_in_ist():
    s = SlotService()
    slot = s.free_slots([], NOW_UTC)[0]
    assert not s.has_started(slot, NOW_UTC)
    assert s.has_started(slot, slot.start + timedelta(minutes=1))


def test_outside_inventory_is_named():
    s = SlotService()
    r = s.parse_requested("2026-09-01T20:00:00+05:30", NOW_UTC)
    assert "10:00" in r.reason and "18:00" in r.reason


def test_free_text_time_is_completed_from_the_ist_date_not_the_server_clock():
    # "4 pm" carries no date. It must land on the IST day of `now` even when the server
    # clock, in US-West, still reads the previous calendar day.
    now_us = NOW_UTC.astimezone(timezone(timedelta(hours=-7)))
    r = SlotService().parse_requested("4 pm", now_us)
    assert isinstance(r, Slot)
    assert r.start == datetime(2026, 9, 1, 16, tzinfo=IST)
