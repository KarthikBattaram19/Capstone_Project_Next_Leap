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
