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
