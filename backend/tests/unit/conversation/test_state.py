import pytest

from scout.conversation.state import IllegalTransition, TurnState, transition


def test_happy_path_type_a():
    s = TurnState.IDLE
    for nxt in (
        TurnState.CAPTURING,
        TurnState.TRANSCRIBING,
        TurnState.ACK,
        TurnState.CLASSIFYING,
        TurnState.TYPE_A,
        TurnState.SPEAKING,
        TurnState.IDLE,
    ):
        s = transition(s, nxt)
    assert s is TurnState.IDLE


def test_barge_in_returns_to_capturing_from_every_active_state():
    # A renter interrupts while the system is thinking, not only while it is speaking.
    for s in (
        TurnState.TRANSCRIBING,
        TurnState.ACK,
        TurnState.CLASSIFYING,
        TurnState.TYPE_A,
        TurnState.TYPE_B,
        TurnState.SPEAKING,
    ):
        assert transition(s, TurnState.CAPTURING) is TurnState.CAPTURING


def test_no_model_before_ack():
    with pytest.raises(IllegalTransition):
        transition(TurnState.TRANSCRIBING, TurnState.TYPE_A)
