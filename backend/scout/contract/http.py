"""The HTTP request and response bodies for booking and the demo availability toggle."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scout.contract.viewmodels import BookingVM, PdfStatus, SlotVM


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlotsRequest(Body):
    listing_id: str


class SlotsResponse(Body):
    slots: list[SlotVM]
    spoken: str


class BookingRequest(Body):
    session_id: str
    listing_id: str
    slot_start_ist: str
    email: str


class BookingResponse(Body):
    booking: BookingVM
    spoken: str


# GET /bookings/{code}/pdf/status and POST /bookings/{code}/pdf/email (spec §6.7, §6.52).
# `spoken` is shown verbatim: what happened to the email, and what the renter can do about it.
# A comment, not a docstring: a docstring would become a schema description, and no other body
# in the contract carries one.
class PdfStatusResponse(Body):
    code: str
    pdf_status: PdfStatus
    spoken: str


class CancelRequest(Body):
    code: str = Field(pattern=r"^[A-Z0-9]{6}$")


class RescheduleRequest(Body):
    code: str = Field(pattern=r"^[A-Z0-9]{6}$")
    slot_start_ist: str


class AvailabilityToggle(Body):
    listing_id: str
    available: bool
