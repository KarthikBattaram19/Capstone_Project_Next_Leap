from datetime import date

from scout.domain.listing import (
    SCHEMA_FIELDS,
    BhkType,
    Coordinates,
    Listing,
    ListingRecord,
    Parking,
)
from scout.domain.provenance import Source, Timing


def make_record(**over):
    base = {
        "id": "kor-001",
        "source_url": "file://data/Bangalore_Properties_List.xlsx#row=1",
        "scraped_on": date(2026, 9, 1),
        "locality": "Koramangala",
        "bhk_type": BhkType.BHK2,
        "bedrooms": 2,
        "bathrooms": 2,
        "balconies": 1,
        "rent": 35000,
        "deposit": None,
        "maintenance_charges": None,
        "maintenance_included": None,
        "property_type": "apartment",
        "furnishing": "semi_furnished",
        "square_footage": 1100,
        "area_basis": "unknown",
        "floor": 3,
        "total_floors": 5,
        "lift": True,
        "parking": Parking.BOTH,
        "parking_available": True,
        "amenities": ["gym"],
        "available_from": None,
        "availability_status": True,
        "society_name": "Prestige Acropolis",
        "coordinates": Coordinates(lat=12.93, lng=77.62),
        "merged_from": [],
    }
    base.update(over)
    return ListingRecord(**base)


def test_record_keeps_null_as_null():
    rec = make_record()
    assert rec.deposit is None


def test_listing_wraps_every_field_with_dataset_provenance():
    listing = Listing.from_record(make_record())
    rent = listing.field("rent")
    assert rent.value == 35000 and rent.source is Source.DATASET
    assert rent.timing is Timing.PRECOMPUTED and rent.as_of == date(2026, 9, 1)
    deposit = listing.field("deposit")
    assert deposit.value is None and deposit.source is Source.DATASET  # null, not absent


def test_bhk_type_and_bedrooms_are_held_side_by_side():
    listing = Listing.from_record(make_record(bhk_type=BhkType.BHK3_PLUS, bedrooms=4))
    assert listing.field("bhk_type").value is BhkType.BHK3_PLUS
    assert listing.field("bedrooms").value == 4


def test_unknown_field_name_is_an_error():
    import pytest

    with pytest.raises(KeyError):
        Listing.from_record(make_record()).field("owner_phone")


def test_balconies_is_a_searchable_field():
    listing = Listing.from_record(make_record(balconies=2))
    assert "balconies" in SCHEMA_FIELDS
    assert listing.field("balconies").value == 2


def test_a_bare_parking_yes_never_becomes_a_four_wheeler_claim():
    # The sheet says only Yes/No. `parking` must stay null rather than assert BOTH.
    rec = make_record(parking=None, parking_available=True)
    listing = Listing.from_record(rec)
    assert listing.field("parking").value is None
    assert listing.field("parking_available").value is True


def test_every_schema_field_exists_on_the_record():
    rec = make_record()
    for name in SCHEMA_FIELDS:
        assert hasattr(rec, name), name


def test_society_type_is_a_searchable_field():
    from scout.domain.listing import SocietyType

    listing = Listing.from_record(make_record(society_type=SocietyType.GATED))
    assert "society_type" in SCHEMA_FIELDS
    assert listing.field("society_type").value is SocietyType.GATED


def test_an_unknown_column_is_refused_rather_than_dropped():
    import pytest

    # A future sheet must not be able to smuggle a name or a phone number through.
    with pytest.raises(Exception) as e:
        make_record(owner_phone="9876543210")
    assert "owner_phone" in str(e.value)
