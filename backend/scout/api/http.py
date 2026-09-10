from fastapi import APIRouter, Header, HTTPException, Request

from scout.booking.service import (
    AlreadyStarted,
    NoSlots,
    NotFound,
    SlotTaken,
    Unchanged,
    Withdrawn,
)
from scout.contract import CONTRACT_VERSION
from scout.contract.http import (
    AvailabilityToggle,
    BookingRequest,
    BookingResponse,
    RescheduleRequest,
    SlotsRequest,
    SlotsResponse,
)
from scout.engines.slots import OutsideInventory

router = APIRouter()

NOT_FOUND_TELL = "No matching visit was found for that code."  # identical for unknown and cancelled


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "contract_version": CONTRACT_VERSION}


@router.get("/contract")
def contract() -> dict:
    return {"contract_version": CONTRACT_VERSION}


def _limited(request: Request) -> None:
    key = request.client.host if request.client else "?"
    if not request.app.state.code_limiter.allow(key):
        raise HTTPException(429, "Too many code lookups; try again in a minute.")


@router.post("/bookings/slots", response_model=SlotsResponse)
async def slots(body: SlotsRequest, request: Request):
    svc, vm = request.app.state.booking, request.app.state.orchestrator.vm
    r = await svc.offer(body.listing_id)
    if isinstance(r, NoSlots):
        return SlotsResponse(
            slots=[],
            spoken=(
                "There are no free visit slots in the next seven days. "
                "Try another listing, or ask me to check again later."
            ),
        )
    return SlotsResponse(
        slots=[vm.slot(s) for s in r],
        spoken="I can offer " + ", ".join(s.spoken() for s in r) + ". Which suits you?",
    )


@router.post("/bookings", response_model=BookingResponse)
async def book(body: BookingRequest, request: Request):
    svc, vm, slots_svc = (
        request.app.state.booking,
        request.app.state.orchestrator.vm,
        request.app.state.slots,
    )
    slot = slots_svc.parse_requested(body.slot_start_ist, svc.now())
    if isinstance(slot, OutsideInventory):
        raise HTTPException(422, slot.reason)
    r = await svc.confirm(body.listing_id, slot, body.email)
    if isinstance(r, Withdrawn):
        raise HTTPException(409, "That listing is no longer available, so I haven't booked it.")
    if isinstance(r, SlotTaken):
        raise HTTPException(
            409,
            "That hour was just taken. Free now: " + ", ".join(s.spoken() for s in r.alternatives),
        )
    request.app.state.after_booking(r.booking)  # PDF + email, off the interactive path (Task 3.4)
    return BookingResponse(booking=vm.booking(r.booking), spoken=r.tell)


@router.post("/bookings/{code}/cancel")
async def cancel(code: str, request: Request):
    _limited(request)
    r = await request.app.state.booking.cancel(code.upper())
    if isinstance(r, NotFound):
        raise HTTPException(404, NOT_FOUND_TELL)
    if isinstance(r, AlreadyStarted):
        raise HTTPException(409, "That visit has already started, so it can't be cancelled.")
    return {
        "code": code.upper(),
        "state": "cancelled",
        "spoken": "Cancelled. Both calendar entries are being removed.",
    }


@router.post("/bookings/{code}/reschedule", response_model=BookingResponse)
async def reschedule(code: str, body: RescheduleRequest, request: Request):
    _limited(request)
    svc, vm, slots_svc = (
        request.app.state.booking,
        request.app.state.orchestrator.vm,
        request.app.state.slots,
    )
    slot = slots_svc.parse_requested(body.slot_start_ist, svc.now())
    if isinstance(slot, OutsideInventory):
        raise HTTPException(422, slot.reason)
    r = await svc.reschedule(code.upper(), slot)
    if isinstance(r, NotFound):
        raise HTTPException(404, NOT_FOUND_TELL)
    if isinstance(r, AlreadyStarted):
        raise HTTPException(409, "That visit has already started, so it can't be moved.")
    if isinstance(r, SlotTaken):
        raise HTTPException(
            409, "That hour is taken. Free now: " + ", ".join(s.spoken() for s in r.alternatives)
        )
    if isinstance(r, Unchanged):
        return BookingResponse(
            booking=vm.booking(r.booking),
            spoken="That's the slot you already have — nothing changed.",
        )
    request.app.state.after_booking(r.booking)
    return BookingResponse(booking=vm.booking(r.booking), spoken=r.tell)


@router.post("/admin/availability")
async def toggle(
    body: AvailabilityToggle, request: Request, x_operator_token: str = Header(default="")
):
    if x_operator_token != request.app.state.settings.operator_token:
        raise HTTPException(401, "operator token required")
    request.app.state.availability.set(body.listing_id, body.available)
    return {"listing_id": body.listing_id, "available": body.available}
