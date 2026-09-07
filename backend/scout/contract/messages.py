"""The WebSocket frames, both directions (arch §11.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from scout.contract.outcome import TurnOutcome


class Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HelloIn(Msg):
    type: Literal["hello"] = "hello"
    contract_version: str


class HelloOut(Msg):
    type: Literal["hello"] = "hello"
    contract_version: str
    session_id: str


class TextIn(Msg):
    type: Literal["text"] = "text"
    text: str


class TranscriptMsg(Msg):
    type: Literal["transcript"] = "transcript"
    text: str
    final: bool


class AckMsg(Msg):
    type: Literal["ack"] = "ack"
    text: str
    state: Literal["processing"] = "processing"


class AudioOutMsg(Msg):
    type: Literal["audio_out"] = "audio_out"
    event: Literal["start", "end", "stop"]
    sample_rate: int | None = None
    format: Literal["pcm16"] | None = None


class OutcomeMsg(Msg):
    type: Literal["outcome"] = "outcome"
    outcome: TurnOutcome
