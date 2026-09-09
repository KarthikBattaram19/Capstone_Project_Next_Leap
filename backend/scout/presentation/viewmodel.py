"""Turn facts into exactly what the screen shows. The frontend derives nothing (AD-5, spec §4)."""

from __future__ import annotations

from scout.contract.viewmodels import (
    NOT_STATED,
    BookingVM,
    CardVM,
    CitationVM,
    CommuteRowVM,
    LocalityGroupVM,
    ShortlistVM,
    SlotVM,
    UnknownGroupVM,
)
from scout.domain.commute_format import render_commute
from scout.domain.constraints import CommutePoint
from scout.domain.provenance import Provenanced, Source
from scout.domain.shortlist import Shortlist


def rupees(n: int | None) -> str:
    """Indian grouping: the last three digits, then pairs. ₹2,00,000, never ₹200,000."""
    if n is None:
        return NOT_STATED
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join([*parts, tail])


def _txt(v) -> str:
    if v is None:
        return NOT_STATED
    if hasattr(v, "value"):  # an enum
        return str(v.value).replace("_", " ")
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


FIELD_LABELS = {
    "parking_required": "parking",
    "deposit_max": "deposit",
    "lift_required": "lift",
    "square_footage_min": "size",
    "available_by": "move-in date",
    "amenities_required": "amenities",
    "furnishing": "furnishing",
    "property_type": "property type",
    "bhk_type": "BHK",
}


class ViewModelBuilder:
    def __init__(self, store, commute) -> None:
        self._store, self._commute = store, commute

    def _row(self, fact, what: str) -> CommuteRowVM:
        r = render_commute(fact, what)
        return CommuteRowVM(
            what=what,
            value_text=r.value_text,
            badge=r.badge,
            full_label=r.full_label,
            spoken=r.spoken,
        )

    def card(self, listing_id: str, rank: int, commute_point: CommutePoint | None) -> CardVM:
        listing = self._store.listings[listing_id]
        f = listing.field

        sqft, basis = f("square_footage").value, f("area_basis").value
        if sqft is None:
            sq = NOT_STATED
        else:
            sq = f"{sqft} sq ft"
            if basis is not None and basis.value != "unknown":
                sq += f" ({basis.value.replace('_', '-')})"

        maint_inc, maint = f("maintenance_included").value, f("maintenance_charges").value
        if maint_inc:
            maintenance = "included in rent"
        elif maint is not None:
            maintenance = f"{rupees(maint)} / month"
        else:
            maintenance = NOT_STATED

        floor, total = f("floor").value, f("total_floors").value
        if floor is None:
            floor_txt = NOT_STATED
        elif total is not None:
            floor_txt = f"{floor} of {total}"
        else:
            floor_txt = str(floor)

        parking_value = f("parking").value
        if parking_value is not None:
            parking = _txt(parking_value)
        elif f("parking_available").value is True:
            # A source may say parking exists without saying which kind. Never guess.
            parking = "available, kind not stated"
        elif f("parking_available").value is False:
            parking = "none"
        else:
            parking = NOT_STATED

        return CardVM(
            listing_id=listing_id,
            rank=rank,
            locality=listing.locality,
            society_name=_txt(f("society_name").value),
            rent=(
                f"{rupees(f('rent').value)} / month" if f("rent").value is not None else NOT_STATED
            ),
            deposit=rupees(f("deposit").value),
            maintenance=maintenance,
            bhk_type=_txt(f("bhk_type").value),
            square_footage=sq,
            floor=floor_txt,
            parking=parking,
            furnishing=_txt(f("furnishing").value),
            amenities=list(f("amenities").value or []),
            available_from=_txt(f("available_from").value),
            transit=self._row(self._commute.transit(listing_id), "Metro"),
            your_commute=(
                self._row(self._commute.to_point(listing_id, commute_point), "Work")
                if commute_point
                else None
            ),
        )

    def shortlist(self, s: Shortlist, commute_point: CommutePoint | None) -> ShortlistVM:
        cards = [self.card(e.listing_id, e.rank, commute_point) for e in s.matched]
        groups: dict[str, list[CardVM]] = {}
        for c in cards:  # first-appearance order of the ranked list; grouping never reorders
            groups.setdefault(c.locality, []).append(c)
        unknown = [
            UnknownGroupVM(
                field=fld,
                listing_ids=list(ids),
                spoken=(
                    f"{len(ids)} more where the {FIELD_LABELS.get(fld, fld)} is not stated — "
                    "want to see them?"
                ),
            )
            for fld, ids in s.unknown.items()
        ]
        return ShortlistVM(
            order=s.order,
            groups=[LocalityGroupVM(locality=k, count=len(v), cards=v) for k, v in groups.items()],
            unknown_on=unknown,
        )

    def citation(self, fact: Provenanced, listing_id: str | None = None) -> CitationVM:
        ref = fact.citation_ref or "none"
        if fact.source is Source.DATASET:
            rec = self._store.listing_records[listing_id]
            return CitationVM(
                ref=ref,
                label=f"[dataset — {rec.society_name or rec.id}, as of {rec.scraped_on.isoformat()}]",
                url=rec.source_url,
                timing="PRECOMPUTED",
                as_of=rec.scraped_on.isoformat(),
            )
        if fact.source in (Source.OSM, Source.COMPUTED):
            r = (
                render_commute(fact, "Metro")
                if hasattr(fact.value, "metres") or fact.value is None
                else None
            )
            label = (
                r.full_label
                if r
                else f"[OSM — precomputed {fact.as_of.isoformat() if fact.as_of else ''}]"
            )
            return CitationVM(
                ref=ref,
                label=label,
                method=fact.method.value if fact.method else None,
                timing=fact.timing.value,
                as_of=fact.as_of.isoformat() if fact.as_of else None,
            )
        if fact.source is Source.GUIDE:
            ch = fact.value
            return CitationVM(
                ref=ref,
                label=f"[{ch.title} — {ch.locality}]",
                title=ch.title,
                url=ch.url,
                timing="PRECOMPUTED",
                as_of=ch.fetched_on.isoformat(),
            )
        return CitationVM(ref=ref, label="[no source — declared unavailable]")

    def slot(self, slot) -> SlotVM:
        return SlotVM(
            start_ist=slot.start.isoformat(), end_ist=slot.end.isoformat(), spoken=slot.spoken()
        )

    def booking(self, b) -> BookingVM:
        return BookingVM(
            code=b.code,
            listing_id=b.listing_id,
            slot=self.slot(b.slot),
            state=b.state.value,
            pdf_status=b.pdf_status,
            calendar_sync="complete" if b.calendar_complete else "reconciling",
        )
