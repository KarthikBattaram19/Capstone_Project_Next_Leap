"""Export the whole contract as one JSON Schema; the frontend generates its types from it."""

from __future__ import annotations

import json
import sys

from pydantic import BaseModel, ConfigDict
from pydantic.json_schema import GenerateJsonSchema

from scout.contract import CONTRACT_VERSION
from scout.contract.http import (
    AvailabilityToggle,
    BookingRequest,
    BookingResponse,
    CancelRequest,
    RescheduleRequest,
    SlotsRequest,
    SlotsResponse,
)
from scout.contract.messages import (
    AckMsg,
    AudioOutMsg,
    HelloIn,
    HelloOut,
    OutcomeMsg,
    TextIn,
    TranscriptMsg,
)


class Contract(BaseModel):
    """A root model whose fields pull every message and body into one $defs table."""

    model_config = ConfigDict(extra="forbid", title=f"scout-contract-v{CONTRACT_VERSION}")

    hello_in: HelloIn
    hello_out: HelloOut
    text_in: TextIn
    transcript: TranscriptMsg
    ack: AckMsg
    audio_out: AudioOutMsg
    outcome: OutcomeMsg
    slots_request: SlotsRequest
    slots_response: SlotsResponse
    booking_request: BookingRequest
    booking_response: BookingResponse
    cancel_request: CancelRequest
    reschedule_request: RescheduleRequest
    availability_toggle: AvailabilityToggle


def export_schema() -> dict:
    # pydantic 2.13.5, inspected 2026-09-07: BaseModel.model_json_schema(by_alias=True,
    # ref_template='#/$defs/{model}', schema_generator=GenerateJsonSchema, mode='validation',
    # *, union_format='any_of').
    schema = Contract.model_json_schema(schema_generator=GenerateJsonSchema, mode="serialization")
    schema["contract_version"] = CONTRACT_VERSION
    return schema


if __name__ == "__main__":
    # CI diffs this output against contract/v1.schema.json byte for byte. On Windows a
    # text-mode stdout turns every "\n" into "\r\n" (measured: 1,165 extra bytes), so pin
    # the line ending and the encoding; on Linux this changes nothing.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    json.dump(export_schema(), sys.stdout, indent=2, sort_keys=True)
