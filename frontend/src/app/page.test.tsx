/**
 * The page's own websocket handlers, driven end to end: a Stop, then the next reply.
 *
 * Production, 2026-09-18, twice in two voice sessions: the renter tapped Stop while a
 * reply was still playing, asked another question, and heard nothing — while the server
 * logged that the turn produced audio. The suspect was `stalled`, which `stopSpeaking`
 * sets to drop the chunks of the interrupted reply still in flight and which only
 * `onAudioStart` clears. These tests replay the sequence; they go silent (nothing
 * reaches the speakers at all) if that flag is ever left set, and they pass as the page
 * stands — so a Stop is not on its own what silenced her.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TurnOutcome } from "@/lib/viewmodels/contract";

/** The microphone double, so the page's mute / un-mute is observable. */
const reg = vi.hoisted(() => ({ mic: null as null | { muted: boolean } }));

vi.mock("@/lib/audio/capture", () => {
  class MicError extends Error {
    constructor(public kind: string) {
      super(kind);
    }
  }
  class MicCapture {
    muted = false;
    onDeviceLost: (() => void) | null = null;
    constructor() {
      reg.mic = this;
    }
    async start() {}
    mute() {
      this.muted = true;
    }
    unmute() {
      this.muted = false;
    }
    async pause() {}
    async resume() {}
    stop() {}
  }
  return { MicCapture, MicError };
});

/** A WebSocket double: the test plays the server, through the page's real WsClient. */
class FakeSocket {
  static last: FakeSocket | null = null;
  static OPEN = 1;
  readyState = 0;
  binaryType = "blob";
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.last = this;
  }
  send(d: unknown) {
    if (typeof d === "string") this.sent.push(d);
  }
  close() {
    this.readyState = 3;
    this.onclose?.({ code: 1000, reason: "" });
  }
  opens() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
    this.json({ type: "hello", contract_version: "1", session_id: "s1" });
  }
  json(m: unknown) {
    this.onmessage?.({ data: JSON.stringify(m) });
  }
  bytes(b: ArrayBuffer) {
    this.onmessage?.({ data: b });
  }
}

class FakeBuffer {
  constructor(
    public length: number,
    private rate: number,
  ) {}
  get duration() {
    return this.length / this.rate;
  }
  getChannelData() {
    return new Float32Array(this.length);
  }
}

/** Stands in for the browser's audio output: what was scheduled, and what was killed. */
class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state = "suspended";
  currentTime = 0;
  destination = {};
  sampleRate: number;
  /** One entry per PCM buffer handed to the speakers. */
  played: { at: number; samples: number }[] = [];
  /** Scheduled buffers that were stopped before they finished — a cut-off reply. */
  cut = 0;
  constructor(opts?: { sampleRate?: number }) {
    this.sampleRate = opts?.sampleRate ?? 48000;
    FakeAudioContext.instances.push(this);
  }
  async resume() {
    this.state = "running";
  }
  async suspend() {
    this.state = "suspended";
  }
  close() {
    this.state = "closed";
  }
  createBuffer(_channels: number, length: number, rate: number) {
    return new FakeBuffer(length, rate);
  }
  createBufferSource() {
    return new FakeSource(this);
  }
}

class FakeSource {
  buffer: FakeBuffer | null = null;
  private done = false;
  constructor(private ctx: FakeAudioContext) {}
  connect() {}
  start(at: number) {
    this.ctx.played.push({ at, samples: this.buffer?.length ?? 0 });
  }
  stop() {
    if (!this.done) this.ctx.cut += 1;
    this.done = true;
  }
}

const RATE = 24000;
/** 240 samples = 10 ms of PCM16 at 24 kHz. */
const chunk = () => new ArrayBuffer(480);

const answered = {
  kind: "answered",
  spoken: "Here are three places in Indiranagar.",
  view_model: {},
} as unknown as TurnOutcome;

const START = { type: "audio_out", event: "start", sample_rate: RATE, format: "pcm16" };
const END = { type: "audio_out", event: "end" };
const STOP = { type: "audio_out", event: "stop" };

const speakers = () => FakeAudioContext.instances[FakeAudioContext.instances.length - 1];
const stopButton = () => screen.queryByRole("button", { name: "Stop speaking" });

async function startSession() {
  const Page = (await import("./page")).default;
  render(<Page />);
  // The click unlocks audio first (an await), so the socket exists only after it.
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Tap to talk to Nakshatra" }));
  });
  await act(async () => {
    FakeSocket.last!.opens();
  });
  return FakeSocket.last!;
}

/** A lane-A reply: ack, the outcome, then the speech. */
function replyA(ws: FakeSocket, chunks = 3) {
  act(() => {
    ws.json({ type: "ack", text: "" });
    ws.json({ type: "outcome", outcome: answered });
    ws.json(START);
  });
  for (let i = 0; i < chunks; i++) act(() => ws.bytes(chunk()));
  act(() => ws.json(END));
}

/**
 * A lane-B reply ("why this one?"): the opener is spoken while Job 2 is still writing, so
 * the speech starts BEFORE the outcome and the outcome lands mid-reply — the order
 * `orchestrator._lane_b` produces, and the shape of the turn that went unheard.
 */
function replyB(ws: FakeSocket, chunks = 3) {
  act(() => {
    ws.json({ type: "ack", text: "" });
    ws.json(START);
  });
  for (let i = 0; i < chunks; i++) act(() => ws.bytes(chunk()));
  act(() => ws.json({ type: "outcome", outcome: answered }));
  for (let i = 0; i < chunks; i++) act(() => ws.bytes(chunk()));
  act(() => ws.json(END));
}

describe("Stop, then the next reply", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    FakeAudioContext.instances = [];
    FakeSocket.last = null;
    reg.mic = null;
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ status: "ok" }) })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("a lane-A reply after a Stop is heard whole, and the mic listens again", async () => {
    const ws = await startSession();
    replyA(ws);
    const heard = speakers().played.length;
    expect(heard).toBe(3);

    // The tap lands after the server has finished sending (it logged `state=idle`): the
    // page still has this reply queued, so the Stop control is still on screen.
    fireEvent.click(stopButton()!);
    expect(ws.sent.some((m) => m.includes('"stop"'))).toBe(true);
    expect(reg.mic!.muted).toBe(false); // D2: she can be heard at once
    // The server answers the stop frame: Speaker.cancel() sends `audio_out stop`.
    act(() => ws.json(STOP));
    const cutByStop = speakers().cut;

    // She asks the next question; the server acks, answers and speaks it.
    act(() => ws.json({ type: "transcript", text: "what about Indiranagar?", final: true }));
    replyA(ws);

    expect(speakers().played.length - heard).toBe(3); // every chunk reached the speakers
    expect(speakers().cut).toBe(cutByStop); // and none of it was killed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(reg.mic!.muted).toBe(false);
  });

  it("a lane-B reply after a Stop is heard whole, outcome mid-reply and all", async () => {
    const ws = await startSession();
    replyB(ws);
    const heard = speakers().played.length;
    expect(heard).toBe(6);

    act(() => ws.json(START)); // the next sentence of that answer starts
    fireEvent.click(stopButton()!);
    act(() => ws.json(STOP));
    const cutByStop = speakers().cut;

    act(() => ws.json({ type: "transcript", text: "why the second one?", final: true }));
    replyB(ws);
    expect(speakers().played.length - heard).toBe(6);
    expect(speakers().cut).toBe(cutByStop);
  });

  /**
   * Production, 2026-09-18: all three Stop clicks in three sessions reached the server as
   * `state=idle` — the server had finished sending and the page was still playing several
   * seconds of buffered audio. The control has to be there for the whole audible window,
   * and on a lane-B reply the outcome lands in the MIDDLE of that window.
   */
  it("keeps the Stop control on screen for as long as she is audible", async () => {
    const ws = await startSession();
    act(() => {
      ws.json({ type: "ack", text: "" });
      ws.json(START);
    });
    for (let i = 0; i < 3; i++) act(() => ws.bytes(chunk()));
    expect(stopButton()).not.toBeNull();

    // Lane B: the outcome arrives while the opener is still playing. It ends the TURN,
    // not the speech — the renter can still hear her, so Stop must still be there.
    act(() => ws.json({ type: "outcome", outcome: answered }));
    expect(stopButton()).not.toBeNull();

    for (let i = 0; i < 3; i++) act(() => ws.bytes(chunk()));
    // The server has finished SENDING; the browser still has the queue to play.
    act(() => ws.json(END));
    expect(stopButton()).not.toBeNull();

    // A click here silences her at once: every buffer still queued is killed.
    fireEvent.click(stopButton()!);
    expect(speakers().cut).toBe(6);
    expect(reg.mic!.muted).toBe(false);
    expect(stopButton()).toBeNull();
  });

  it("drops the Stop control once the last buffer has played", async () => {
    const ws = await startSession();
    replyA(ws);
    expect(stopButton()).not.toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(stopButton()).toBeNull();
    expect(reg.mic!.muted).toBe(false);
  });

  // The server logs a Stop that arrives with nothing to cancel as `barge-in state=idle`.
  // When the server has stopped sending AND the speakers have drained, there is nothing
  // left to stop anywhere: the page keeps that frame to itself.
  it("sends no stop frame when the server has finished and nothing is left to play", async () => {
    const ws = await startSession();
    replyA(ws);
    // The audio clock runs past the last buffer, but the un-mute timer has not fired yet,
    // so the control is still on screen for another moment.
    speakers().currentTime = 10;
    fireEvent.click(stopButton()!);
    expect(ws.sent.filter((m) => m.includes('"stop"'))).toEqual([]);
  });

  // The one way the page silences a reply it has started: the server says so. This is
  // barge-in working as designed — but after a Stop the mic is live from the tap until
  // the next `audio_out start`, a far longer window than any ordinary turn, so a stray
  // word landing in it cancels the new reply the renter is waiting to hear.
  it("an audio_out stop mid-reply kills what is already queued", async () => {
    const ws = await startSession();
    act(() => {
      ws.json({ type: "ack", text: "" });
      ws.json({ type: "outcome", outcome: answered });
      ws.json(START);
    });
    for (let i = 0; i < 3; i++) act(() => ws.bytes(chunk()));
    expect(speakers().cut).toBe(0);
    act(() => ws.json(STOP));
    expect(speakers().cut).toBe(3); // three chunks queued, none of them heard
    expect(reg.mic!.muted).toBe(false);
    expect(stopButton()).toBeNull();
  });
});

/**
 * The page half of the rule the server states in `a609e39`: "SPEAKING is the window in
 * which audio is actually going out, and it does not coincide with the page's playback
 * window at either edge." The server's half depends on this end behaving exactly so, and
 * nothing here changes D2 — the mic stays muted for the whole of playback.
 */
describe("when she has stopped speaking: the page half of the rule", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    FakeAudioContext.instances = [];
    FakeSocket.last = null;
    reg.mic = null;
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ status: "ok" }) })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  // Leading edge: the server counts itself SPEAKING only from the first byte, because
  // until then the page has not muted and the renter is still free to talk.
  it("leaves the mic open until the first byte, then mutes on it", async () => {
    const ws = await startSession();
    act(() => ws.json({ type: "ack", text: "" }));
    expect(reg.mic!.muted).toBe(false);
    act(() => ws.json({ type: "outcome", outcome: answered }));
    expect(reg.mic!.muted).toBe(false); // the reply is written but not a sound of it yet
    act(() => ws.json(START));
    expect(reg.mic!.muted).toBe(true); // muted before the first chunk plays
  });

  // Trailing edge: the server is IDLE from its last byte, the page is still playing, and
  // the mic stays shut until the speakers are empty (D2) — not when the sending stops.
  it("keeps the mic shut until the last buffer has played, not until audio_out end", async () => {
    const ws = await startSession();
    replyA(ws);
    expect(reg.mic!.muted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100); // inside the queue's remaining 30 ms + 150 ms
    });
    expect(reg.mic!.muted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(reg.mic!.muted).toBe(false);
    // And a Stop in that window is still worth sending: the server cancels from IDLE.
    const ws2 = await startSession();
    replyA(ws2);
    fireEvent.click(stopButton()!);
    expect(ws2.sent.filter((m) => m.includes('"stop"')).length).toBe(1);
  });

  // "One speaker at a time": new speech stops the speech still going out and the page is
  // told to drop what it is playing. What it drops has to include the tail of that reply —
  // a chunk already on its way — or the cancelled reply plays over the new one.
  it("drops the tail of a cancelled reply instead of playing it over the next one", async () => {
    const ws = await startSession();
    act(() => {
      ws.json({ type: "ack", text: "" });
      ws.json({ type: "outcome", outcome: answered });
      ws.json(START);
    });
    for (let i = 0; i < 3; i++) act(() => ws.bytes(chunk()));
    act(() => ws.json(STOP));
    const heard = speakers().played.length;

    act(() => ws.bytes(chunk())); // a straggler from the reply that was just cancelled
    expect(speakers().played.length).toBe(heard);

    // The reply that replaced it is heard whole.
    replyA(ws);
    expect(speakers().played.length).toBe(heard + 3);
  });
});
