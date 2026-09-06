"""One utterance must produce exactly one turn.

Deepgram sends `is_final=True` every time it FINALISES A SEGMENT, which happens
several times inside one spoken sentence — at every natural pause. Only
`speech_final=True` means "the person stopped talking" (that is what the 400 ms
endpointing setting produces). The skeleton treated every is_final as a complete
utterance, so one sentence started several turns at once, each streaming its own
TTS audio into the same browser socket. Observed on the deployed service on
2026-09-06: two spoken utterances produced fourteen turns.

Verified against deepgram-sdk 7.8.0 on 2026-09-06 by streaming a real utterance:
both fields exist, and for a clean sentence they go
    (False, False) x4 interims -> (True, True) -> (False, False) empty
so a segment final (True, False) is the case this routing must not mistake for
the end of an utterance.
"""

from types import SimpleNamespace

from scout.config import Settings
from scout.providers.deepgram_stt import DeepgramStream


def message(transcript, *, is_final=False, speech_final=False, kind="Results"):
    return SimpleNamespace(
        type=kind,
        is_final=is_final,
        speech_final=speech_final,
        channel=SimpleNamespace(alternatives=[SimpleNamespace(transcript=transcript)]),
    )


def stream(finals, interims, utterance_ends=None):
    async def on_final(t):
        finals.append(t)

    async def on_interim(t):
        interims.append(t)

    async def noop():
        if utterance_ends is not None:
            utterance_ends.append(True)

    return DeepgramStream(
        Settings(_env_file=None),
        keyterms=[],
        on_interim=on_interim,
        on_final=on_final,
        on_speech_started=noop,
        on_utterance_end=noop,
    )


async def test_a_segment_final_does_not_start_a_turn():
    finals, interims = [], []
    st = stream(finals, interims)

    await st._on_message(message("two BHK in Koramangala", is_final=True, speech_final=False))

    assert finals == [], f"a mid-sentence segment must not end the turn; got {finals}"


async def test_the_whole_utterance_is_delivered_once_speech_ends():
    # Each message carries only its own segment, so the segments have to be joined — otherwise the turn acts on "need parking" and loses the budget,
    # the locality and the bedroom count.
    finals, interims = [], []
    st = stream(finals, interims)

    await st._on_message(message("two BHK in Koramangala", is_final=True))
    await st._on_message(message("under forty thousand", is_final=True))
    await st._on_message(message("need parking", is_final=True, speech_final=True))
    await st._on_message(message("", kind="UtteranceEnd"))

    assert finals == ["two BHK in Koramangala under forty thousand need parking"], finals


async def test_utterance_end_flushes_what_was_heard():
    # P3b: if endpointing never fires, the 1 s hard stop must still deliver the turn
    # rather than leaving the renter's sentence stranded.
    finals, interims = [], []
    st = stream(finals, interims)

    await st._on_message(message("two BHK in Koramangala", is_final=True))
    await st._on_message(message("", kind="UtteranceEnd"))

    assert finals == ["two BHK in Koramangala"], finals


async def test_a_second_utterance_starts_clean():
    finals, interims = [], []
    st = stream(finals, interims)

    await st._on_message(message("first one", is_final=True, speech_final=True))
    await st._on_message(message("", kind="UtteranceEnd"))
    await st._on_message(message("second one", is_final=True, speech_final=True))
    await st._on_message(message("", kind="UtteranceEnd"))

    assert finals == ["first one", "second one"], finals


async def test_speech_final_starts_the_turn_without_waiting_for_utterance_end():
    """The turn starts on speech_final; pause tolerance lives in the endpointing value.

    Measured against Deepgram on 2026-09-06, real-time paced, 3 runs each, on a fluent
    sentence and on one with a ~1 s mid-sentence breath:

        trigger                     fluent      with a breath
        UtteranceEnd (any ep)       ~+1.7 s     ~+1.7 s, whole
        speech_final @  700 ms      +1.0 s      SPLITS
        speech_final @  800 ms      +1.05 s     SPLITS
        speech_final @ 1000 ms      +1.3 s      +1.3 s, whole

    speech_final at 1000 ms keeps the breath whole and starts the turn ~0.4 s sooner
    than waiting for UtteranceEnd, so it is the trigger. UtteranceEnd stays as the
    P3b fallback flush for a stream where endpointing never fires.
    """
    finals, interims = [], []
    st = stream(finals, interims)

    await st._on_message(message("two BHK in Koramangala", is_final=True))
    await st._on_message(message("under forty thousand", is_final=True, speech_final=True))

    assert finals == ["two BHK in Koramangala under forty thousand"], finals


def test_default_endpointing_tolerates_a_breath():
    # A 700 ms gap (about 1 s once the surrounding silence is counted) split the
    # sentence at 400 and 800 ms and stayed whole at 1000 ms. The default carries
    # that measurement; Gate L's false-end-of-speech count is where it gets checked on
    # a real Indian-English speaker.
    from scout.config import Settings

    assert Settings(_env_file=None).deepgram_endpointing_ms == 1000
