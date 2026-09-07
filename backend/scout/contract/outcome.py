"""Five shapes. Empty is a RESULT; Failed is an ERROR. They cannot share a renderer (A5)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from scout.contract.viewmodels import AnsweredViewModel

Capability = Literal["speech_in", "understanding", "explanation", "speech_out", "calendar", "mail"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spoken: str  # every outcome is both spoken and shown (spec §6.0 principle 3)


class UnmetConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: str
    binding: bool


class Answered(_Base):
    kind: Literal["answered"] = "answered"
    view_model: AnsweredViewModel


class Empty(_Base):
    kind: Literal["empty"] = "empty"
    unmet: list[UnmetConstraint]
    suggestions: list[str]


class Degraded(_Base):
    kind: Literal["degraded"] = "degraded"
    view_model: AnsweredViewModel
    missing: list[str]
    why: str


class Failed(_Base):
    kind: Literal["failed"] = "failed"
    capability: Capability
    tell_renter: str
    retry_worth_it: bool


class NeedsInput(_Base):
    kind: Literal["needs_input"] = "needs_input"
    question: str
    field: str
    options: list[str] = Field(default_factory=list)


TurnOutcome = Annotated[
    Answered | Empty | Degraded | Failed | NeedsInput, Field(discriminator="kind")
]
