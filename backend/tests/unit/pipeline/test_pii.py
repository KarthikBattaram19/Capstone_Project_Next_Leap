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
