"""E1: Job 2 copies what FACTS says, so FACTS says money the way the renter hears it."""

from datetime import date

from scout.conversation.job2 import SYSTEM, Job2
from scout.domain.provenance import Provenanced, Source, Timing
from scout.grounding.resolvers import FactBundle


def _fact(ref, value):
    return Provenanced(
        value, Source.DATASET, Timing.PRECOMPUTED, as_of=date(2026, 9, 1), citation_ref=ref
    )


def test_money_in_facts_is_formatted_in_rupees_with_indian_grouping():
    b = FactBundle(listing_id="a", locality="Koramangala")
    for name, v in (("rent", 30000), ("deposit", 165000), ("maintenance_charges", 2500)):
        b.facts[f"dataset:a:{name}"] = _fact(f"dataset:a:{name}", v)
    b.facts["dataset:a:bathrooms"] = _fact("dataset:a:bathrooms", 2)
    b.facts["dataset:a:furnishing"] = _fact("dataset:a:furnishing", "semi_furnished")
    user = Job2(client=None).build_user(b, "why this one?")
    assert "dataset:a:rent: ₹30,000 (" in user
    assert "dataset:a:deposit: ₹1,65,000 (" in user
    assert "dataset:a:maintenance_charges: ₹2,500 (" in user
    assert "dataset:a:bathrooms: 2 (" in user
    assert "semi furnished" in user and "semi_furnished" not in user


def test_the_prompt_says_to_copy_money_as_written():
    assert "₹" in SYSTEM
