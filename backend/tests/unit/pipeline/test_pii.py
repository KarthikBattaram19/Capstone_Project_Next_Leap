import pytest

from scout.pipeline.pii import strip_pii


def test_strips_indian_mobile_numbers_in_all_common_forms():
    s = "Call Ramesh on 9876543210 or +91 98765-43210 or 098765 43210 today"
    out = strip_pii(s)
    assert "98765" not in out and "43210" not in out
    assert "[phone removed]" in out


def test_strips_emails():
    assert "@" not in strip_pii("mail owner.name@example.com now")


def test_leaves_rent_and_pincode_alone():
    s = "Rent 35000, deposit 200000, pincode 560034"
    assert strip_pii(s) == s


def test_strips_bare_nine_digit_numbers():
    # The supplied sheet's Phone Number column is nine digits, not the ten an
    # Indian mobile carries. The guard must still catch it.
    out = strip_pii("owner 395862397 call anytime")
    assert "395862397" not in out
    assert "[phone removed]" in out


def test_leaves_a_coordinate_alone():
    s = "12.91285324, 77.57820129"
    assert strip_pii(s) == s


def test_a_clean_payload_passes_the_guard():
    from scout.pipeline.pii import assert_no_pii

    assert_no_pii('[{"id": "jp-nagar-00001", "rent": 35000, "lat": 12.91285324}]', where="bundle")


def test_the_guard_catches_an_email_in_a_payload():
    from scout.pipeline.pii import PiiLeakError, assert_no_pii

    with pytest.raises(PiiLeakError):
        assert_no_pii('{"society_name": "owner.name@example.com"}', where="bundle")


def test_the_guard_catches_a_bare_nine_digit_run():
    # The shape of this sheet's Phone Number column.
    from scout.pipeline.pii import PiiLeakError, assert_no_pii

    with pytest.raises(PiiLeakError):
        assert_no_pii('{"society_name": "owner 395862397"}', where="bundle")


def test_the_guard_names_where_and_the_kind_but_never_echoes_the_value():
    # An error message that prints the leaked number publishes it into the CI log.
    from scout.pipeline.pii import PiiLeakError, assert_no_pii

    with pytest.raises(PiiLeakError) as e:
        assert_no_pii('{"a": "9876543210", "b": "x@y.com"}', where="data/bundle/listings.json")
    msg = str(e.value)
    assert "data/bundle/listings.json" in msg
    assert "phone" in msg and "email" in msg
    assert "9876543210" not in msg and "x@y.com" not in msg


def test_the_guard_leaves_a_real_bundle_row_alone():
    # Coordinates run to eight fraction digits and the widest figure is a six-digit
    # deposit, so nothing legitimate in this source looks like a phone number.
    from scout.pipeline.pii import assert_no_pii

    row = (
        '{"id": "jp-nagar-09185", "source_url": "file://data/Bangalore_Properties_List.xlsx'
        '#row=9185", "scraped_on": "2026-09-05", "rent": 150000, "deposit": 500000, '
        '"square_footage": 3500, "coordinates": {"lat": 12.91285324, "lng": 77.57820129}}'
    )
    assert_no_pii(row, where="bundle")
