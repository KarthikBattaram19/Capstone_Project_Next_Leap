"""The turn's allowed moves (arch §7.1). Every active state can be interrupted (spec §6.17)."""

from __future__ import annotations

from enum import Enum


class TurnState(str, Enum):
    IDLE = "IDLE"
    CAPTURING = "CAPTURING"
    TRANSCRIBING = "TRANSCRIBING"
    ACK = "ACK"
    CLASSIFYING = "CLASSIFYING"
    TYPE_A = "TYPE_A"
    TYPE_B = "TYPE_B"
    SPEAKING = "SPEAKING"


# Every active state has an edge back to CAPTURING, and that edge is barge-in. A renter
# interrupts while the assistant is still THINKING as often as while it is speaking; with
# SPEAKING -> CAPTURING as the only such edge, an utterance arriving in TRANSCRIBING / ACK /
# CLASSIFYING / TYPE_A / TYPE_B was discarded by _finalize's state guard without a word.
# No edge skips the acknowledgement: CAPTURING -> TYPE_A stays illegal, which is what keeps a
# model call out of L1.
TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.IDLE: {TurnState.CAPTURING},
    TurnState.CAPTURING: {TurnState.TRANSCRIBING},
    TurnState.TRANSCRIBING: {TurnState.ACK, TurnState.CAPTURING},
    TurnState.ACK: {TurnState.CLASSIFYING, TurnState.CAPTURING},
    TurnState.CLASSIFYING: {TurnState.TYPE_A, TurnState.TYPE_B, TurnState.CAPTURING},
    TurnState.TYPE_A: {TurnState.SPEAKING, TurnState.CAPTURING},
    TurnState.TYPE_B: {TurnState.SPEAKING, TurnState.CAPTURING},
    TurnState.SPEAKING: {TurnState.IDLE, TurnState.CAPTURING},
}


class IllegalTransition(RuntimeError):
    pass


def transition(state: TurnState, to: TurnState) -> TurnState:
    if to not in TRANSITIONS[state]:
        raise IllegalTransition(f"{state.value} → {to.value}")
    return to
