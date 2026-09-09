import asyncio

from scout.conversation.speaker import Speaker, split_sentences


def test_split_keeps_money_and_abbreviations_intact():
    s = split_sentences(
        "It's ₹35,000 for a 2BHK. About 1.2 km by route to the metro. Shall I book it?"
    )
    assert s == [
        "It's ₹35,000 for a 2BHK.",
        "About 1.2 km by route to the metro.",
        "Shall I book it?",
    ]


class FakeTts:
    sample_rate = 24000

    def __init__(self, fail=False):
        self.fail, self.spoken = fail, []

    async def stream(self, text):
        if self.fail:
            raise RuntimeError("tts down")
        self.spoken.append(text)
        for _ in range(3):
            await asyncio.sleep(0.01)
            yield b"\x00\x01"


class FakeSink:
    def __init__(self):
        self.events = []

    async def audio_start(self):
        self.events.append("start")

    async def audio_chunk(self, b):
        self.events.append("chunk")

    async def audio_end(self):
        self.events.append("end")

    async def audio_stop(self):
        self.events.append("stop")


async def test_first_sentence_starts_before_the_second_is_known():
    tts, sink = FakeTts(), FakeSink()

    async def gen():
        yield "First sentence."
        await asyncio.sleep(0.2)
        yield "Second sentence."

    res = await Speaker(tts, sink).speak(gen())
    assert sink.events[0] == "start"
    assert sink.events.count("chunk") == 6
    assert sink.events[-1] == "end"
    assert not res.cancelled
    assert not res.tts_failed
    assert tts.spoken == ["First sentence.", "Second sentence."]


async def test_cancel_stops_audio_and_sends_stop():
    tts, sink = FakeTts(), FakeSink()
    sp = Speaker(tts, sink)
    task = asyncio.create_task(sp.speak(["One.", "Two.", "Three."]))
    await asyncio.sleep(0.015)
    await sp.cancel()
    res = await task
    assert res.cancelled
    assert "stop" in sink.events
    assert sink.events.count("chunk") < 9


async def test_tts_failure_completes_in_text():
    res = await Speaker(FakeTts(fail=True), FakeSink()).speak(["Hello."])
    assert res.tts_failed and not res.cancelled
