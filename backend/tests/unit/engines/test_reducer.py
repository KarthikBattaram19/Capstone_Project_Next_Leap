from scout.domain.constraints import ConstraintEdit, ConstraintSet
from scout.domain.listing import BhkType, Furnishing, Parking, PropertyType
from scout.engines.reducer import Contradiction, apply_edit, apply_edits, confirm_all


def test_each_edit_changes_exactly_one_field():
    c0 = ConstraintSet()
    c1 = apply_edit(c0, ConstraintEdit("rent_max", "set", 40000))
    c2 = apply_edit(c1, ConstraintEdit("rent_max", "set", 35000))
    c3 = apply_edit(c2, ConstraintEdit("lift_required", "set", "true"))
    assert c3.rent_max == 35000 and c3.lift_required is True
    assert c1 is not c0 and c0.rent_max is None  # never modified in place


def test_localities_accumulate_and_remove():
    c = ConstraintSet()
    for e in (
        ConstraintEdit("localities", "add", "Koramangala"),
        ConstraintEdit("localities", "add", "HSR Layout"),
        ConstraintEdit("localities", "remove", "Koramangala"),
    ):
        c = apply_edit(c, e)
    assert c.localities == ("HSR Layout",)


def test_contradiction_returns_a_question_not_a_broken_filter():
    c = apply_edit(ConstraintSet(), ConstraintEdit("rent_min", "set", 30000))
    r = apply_edit(c, ConstraintEdit("rent_max", "set", 25000))
    assert isinstance(r, Contradiction) and "30,000" in r.question and "25,000" in r.question
    assert c.rent_max is None


def test_enums_are_parsed():
    c = apply_edits(
        ConstraintSet(),
        [
            ConstraintEdit("bhk_type", "set", "2BHK"),
            ConstraintEdit("parking_required", "set", "four_wheeler"),
        ],
    )
    assert c.bhk_type is BhkType.BHK2 and c.parking_required is Parking.FOUR_WHEELER


def test_set_unconfirms_only_that_field():
    c = confirm_all(
        apply_edits(
            ConstraintSet(),
            [
                ConstraintEdit("rent_max", "set", 40000),
                ConstraintEdit("bhk_type", "set", "2BHK"),
            ],
        )
    )
    c2 = apply_edit(c, ConstraintEdit("rent_max", "set", 35000))
    assert "bhk_type" in c2.confirmed and "rent_max" not in c2.confirmed


def test_the_words_renters_actually_say_map_to_the_datasets_vocabulary():
    # Job 1 copies what it heard; the sheet says "semi_furnished", "four_wheeler",
    # "apartment". A voice system hears "semi", "car parking", "flat", "2 BHK".
    c = apply_edits(
        ConstraintSet(),
        [
            ConstraintEdit("furnishing", "set", "semi"),
            ConstraintEdit("parking_required", "set", "car parking"),
            ConstraintEdit("property_type", "set", "flat"),
            ConstraintEdit("bhk_type", "set", "2 BHK"),
        ],
    )
    assert c.furnishing is Furnishing.SEMI_FURNISHED
    assert c.parking_required is Parking.FOUR_WHEELER
    assert c.property_type is PropertyType.APARTMENT
    assert c.bhk_type is BhkType.BHK2


def test_a_word_outside_the_vocabulary_is_still_a_question_not_a_guess():
    r = apply_edit(ConstraintSet(), ConstraintEdit("furnishing", "set", "luxurious"))
    assert isinstance(r, Contradiction) and r.field == "furnishing"


def test_an_unparseable_value_becomes_a_question_not_a_stack_trace():
    # Nothing in lane A catches a ValueError, so an enum, date or amount Job 1 could not
    # normalise must come back as something to ask (eval.md EC-RED-06/07).
    r = apply_edit(ConstraintSet(), ConstraintEdit("bhk_type", "set", "penthouse"))
    assert isinstance(r, Contradiction) and r.field == "bhk_type"
    r2 = apply_edit(ConstraintSet(), ConstraintEdit("available_by", "set", "whenever"))
    assert isinstance(r2, Contradiction) and r2.field == "available_by"


def test_a_size_keeps_its_unit_and_is_still_read():
    # Job 1 copies what it heard: "at least 1274 sq ft" arrives as "1274 sq ft".
    for said in ("1274", "1274 sq ft", "1,274 square feet", " 1274 sqft ", "1274 ft"):
        c = apply_edit(ConstraintSet(), ConstraintEdit("square_footage_min", "set", said))
        assert isinstance(c, ConstraintSet), f"{said!r} became {c}"
        assert c.square_footage_min == 1274, said


def test_a_number_in_the_wrong_field_is_a_question_not_a_guess():
    # "3BHK" landing in a size field is a mis-extraction; 3 sq ft would be worse than asking.
    r = apply_edit(ConstraintSet(), ConstraintEdit("square_footage_min", "set", "3BHK"))
    assert isinstance(r, Contradiction) and r.field == "square_footage_min"


# --- E2 (voice fix batch 2026-09-17): parking means "parking available" ---


def test_a_plain_parking_requirement_is_any_parking_not_a_question():
    """Production, 2026-09-17: "...with a parking facility." -> "I didn't follow the parking
    required — I heard 'true'."; "I'm saying I need parking also." -> the same with 'yes'."""
    for said in ("true", "yes", "True", "parking", "parking facility", "any", "required"):
        c = apply_edit(ConstraintSet(), ConstraintEdit("parking_required", "set", said))
        assert isinstance(c, ConstraintSet), f"{said!r} became {c}"
        assert c.parking_required is True, said


def test_no_parking_needed_asks_for_nothing():
    for said in ("no", "false", "none", "not needed"):
        c = apply_edit(ConstraintSet(), ConstraintEdit("parking_required", "set", said))
        assert isinstance(c, ConstraintSet), f"{said!r} became {c}"
        assert not c.parking_required, said


def test_a_named_kind_of_parking_is_kept():
    c = apply_edit(ConstraintSet(), ConstraintEdit("parking_required", "set", "car parking"))
    assert c.parking_required is Parking.FOUR_WHEELER
    assert c.readback() == ["with parking"]


def test_a_question_about_an_unusable_value_names_no_field_and_no_raw_value():
    bad = {
        "bhk_type": "penthouse",
        "furnishing": "luxurious",
        "property_type": "castle",
        "parking_required": "helipad",
        "rent_max": "whatever",
        "rent_min": "whatever",
        "deposit_max": "whatever",
        "square_footage_min": "3BHK",
        "available_by": "whenever",
    }
    for field, value in bad.items():
        r = apply_edit(ConstraintSet(), ConstraintEdit(field, "set", value))
        assert isinstance(r, Contradiction), field
        q = r.question
        assert "_" not in q, q
        assert "_" not in field or field.replace("_", " ") not in q, q  # "parking required"
        assert value not in q and "heard" not in q, q
