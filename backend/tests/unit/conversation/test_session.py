from datetime import timedelta

from scout.conversation.session import SessionManager
from scout.domain.constraints import ConstraintSet


def test_two_sessions_are_independent():
    m = SessionManager(ttl_s=60)
    a, b = m.create(), m.create()
    a.constraints = a.constraints.with_(rent_max=40000)
    assert b.constraints.rent_max is None and a.id != b.id


def test_idle_sessions_expire():
    m = SessionManager(ttl_s=60)
    s = m.create()
    m.expire_idle(now=s.last_seen + timedelta(seconds=61))
    assert m.get(s.id) is None


def test_readback_lists_only_set_fields():
    c = ConstraintSet().with_(localities=("Koramangala",), rent_max=35000, bhk_type="2BHK")
    rb = c.readback()
    assert any("Koramangala" in x for x in rb) and any("35,000" in x for x in rb) and len(rb) == 3
