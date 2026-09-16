"""Everything the renter can see, already decided. The frontend derives nothing (AD-5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NOT_STATED = "not stated"


class VM(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommuteRowVM(VM):
    what: str  # "Metro" | "Bus stop" | "Work"
    value_text: str  # "1.1 km" | "not stated"
    badge: str  # "by route" | "straight-line" | "" (only when value_text is "not stated")
    full_label: str  # "[OSM routing — precomputed 2026-09-01]" …
    spoken: str


class CardVM(VM):
    listing_id: str
    rank: int
    locality: str  # the card's primary label (spec §4)
    society_name: str
    rent: str
    deposit: str
    maintenance: str
    bhk_type: str
    square_footage: str  # "1100 sq ft (carpet)" | "not stated" — labelled sq ft, never "area"
    floor: str
    parking: str
    furnishing: str
    amenities: list[str]
    available_from: str
    transit: CommuteRowVM
    your_commute: CommuteRowVM | None = None  # absent, not empty, when no commute point was stated


class UnknownGroupVM(VM):
    field: str
    listing_ids: list[str]
    spoken: str  # "3 more where the deposit is not stated — want to see them?"


class LocalityGroupVM(VM):
    locality: str
    count: int
    cards: list[CardVM]


class ShortlistVM(VM):
    order: list[str]  # the ranked order; grouping never reorders it
    groups: list[LocalityGroupVM]
    unknown_on: list[UnknownGroupVM] = Field(default_factory=list)


class CitationVM(VM):
    ref: str  # "dataset:kor-001" | "osm:kor-001:nearest_metro" | "guide:kor-0-3"
    label: str  # "[Wikipedia — Koramangala]" | "[OSM routing — precomputed 2026-09-01]"
    title: str | None = None
    url: str | None = None
    method: str | None = None
    timing: str | None = None
    as_of: str | None = None


class ClaimVM(VM):
    text: str
    citation_refs: list[str]


class SnapshotVM(VM):
    listing_id: str
    claims: list[ClaimVM]
    gaps: list[str]
    limited: bool  # "Limited neighborhood data available"


class ExplanationVM(VM):
    listing_id: str
    opener: str
    claims: list[ClaimVM]
    gaps: list[str]
    sources: list[CitationVM]


class SlotVM(VM):
    start_ist: str  # ISO 8601 with +05:30
    end_ist: str
    spoken: str  # "Tuesday the 2nd at 4 pm"


# The addendum types these three as `str` with the allowed values in a comment. They are
# Literals here because the frontend (Task 3.5) and the booking state machine (Task 3.3)
# branch on the exact values, and a Literal carries them into the exported schema.
BookingState = Literal["offered", "confirming", "booked", "cancelled", "withdrawn"]
# render_failed and rate_limited are §6.51 and §6.52: the sender always produced them, but the
# contract did not carry them, so a view built from either would have failed validation.
PdfStatus = Literal["pending", "sent", "failed", "render_failed", "rate_limited", "not_applicable"]
CalendarSync = Literal["complete", "reconciling"]


class BookingVM(VM):
    code: str
    listing_id: str
    slot: SlotVM
    state: BookingState  # offered | confirming | booked | cancelled | withdrawn
    pdf_status: PdfStatus  # pending | sent | failed | render_failed | rate_limited | not_applicable
    calendar_sync: CalendarSync  # complete | reconciling


class AnsweredViewModel(VM):
    constraints_readback: list[str] = Field(default_factory=list)
    shortlist: ShortlistVM | None = None
    explanation: ExplanationVM | None = None
    snapshot: SnapshotVM | None = None
    booking: BookingVM | None = None
    offered_slots: list[SlotVM] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)  # e.g. "One listing … has been removed."
