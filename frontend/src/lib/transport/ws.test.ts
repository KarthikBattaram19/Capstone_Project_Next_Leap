import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ContractMismatchError, WsClient } from "./ws";

/** A WebSocket double that lets the test drive open / message / close by hand. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  binaryType = "blob";
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(d: string) {
    this.sent.push(d);
  }
  close() {
    this.readyState = 3;
    this.onclose?.({ code: 1000, reason: "" });
  }
  // test helpers
  serverOpens() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
    this.onmessage?.({ data: JSON.stringify({ type: "hello", contract_version: "1" }) });
  }
  serverDrops(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code, reason: "" });
  }
}

describe("WsClient reconnect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("a contract mismatch names itself and never reconnects", async () => {
    const c = new WsClient("ws://x/ws");
    const closed: string[] = [];
    c.onClosed = (r) => closed.push(r);
    const p = c.connect();
    FakeSocket.instances[0].onclose?.({ code: 4400, reason: "contract_version_mismatch" });
    await expect(p).rejects.toBeInstanceOf(ContractMismatchError);
    expect(closed).toEqual(["contract_version_mismatch"]);
    await vi.advanceTimersByTimeAsync(10000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("an unexpected drop retries at 1 s, 2 s, 4 s and then reports unreachable", async () => {
    const c = new WsClient("ws://x/ws");
    const closed: string[] = [];
    const attempts: number[] = [];
    c.onClosed = (r) => closed.push(r);
    c.onReconnecting = (n) => attempts.push(n);
    const p = c.connect();
    FakeSocket.instances[0].serverOpens();
    await p;

    FakeSocket.instances[0].serverDrops();
    expect(attempts).toEqual([1]);
    expect(FakeSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeSocket.instances).toHaveLength(2);

    FakeSocket.instances[1].serverDrops();
    await vi.advanceTimersByTimeAsync(2000);
    expect(FakeSocket.instances).toHaveLength(3);

    FakeSocket.instances[2].serverDrops();
    await vi.advanceTimersByTimeAsync(4000);
    expect(FakeSocket.instances).toHaveLength(4);

    FakeSocket.instances[3].serverDrops();
    expect(closed).toEqual(["unreachable"]);
    expect(attempts).toEqual([1, 2, 3]);
  });

  it("a successful reconnect resends hello and resets the attempt count", async () => {
    const c = new WsClient("ws://x/ws");
    let opens = 0;
    c.onOpen = () => opens++;
    const p = c.connect();
    FakeSocket.instances[0].serverOpens();
    await p;
    FakeSocket.instances[0].serverDrops();
    await vi.advanceTimersByTimeAsync(1000);
    FakeSocket.instances[1].serverOpens();
    expect(opens).toBe(2);
    expect(FakeSocket.instances[1].sent[0]).toContain('"hello"');
    // Another drop starts the ladder again from 1 s, not from the 3rd rung.
    const attempts: number[] = [];
    c.onReconnecting = (n) => attempts.push(n);
    FakeSocket.instances[1].serverDrops();
    expect(attempts).toEqual([1]);
  });

  it("a first connection that never opens keeps connect() pending through the ladder, then rejects", async () => {
    const c = new WsClient("ws://x/ws");
    const closed: string[] = [];
    c.onClosed = (r) => closed.push(r);
    let settled: string | null = null;
    const p = c.connect().then(
      () => (settled = "resolved"),
      (e: Error) => (settled = e.message),
    );
    FakeSocket.instances[0].serverDrops();
    await vi.advanceTimersByTimeAsync(1000);
    expect(settled).toBeNull(); // still trying
    FakeSocket.instances[1].serverDrops();
    await vi.advanceTimersByTimeAsync(2000);
    FakeSocket.instances[2].serverDrops();
    await vi.advanceTimersByTimeAsync(4000);
    FakeSocket.instances[3].serverDrops();
    await p;
    expect(settled).toBe("unreachable");
    expect(closed).toEqual(["unreachable"]);
  });

  it("a first connection that opens on the second try resolves connect()", async () => {
    const c = new WsClient("ws://x/ws");
    const p = c.connect();
    FakeSocket.instances[0].serverDrops();
    await vi.advanceTimersByTimeAsync(1000);
    FakeSocket.instances[1].serverOpens();
    await expect(p).resolves.toBeUndefined();
  });

  it("closing on purpose does not reconnect", async () => {
    const c = new WsClient("ws://x/ws");
    const closed: string[] = [];
    c.onClosed = (r) => closed.push(r);
    const p = c.connect();
    FakeSocket.instances[0].serverOpens();
    await p;
    c.close();
    await vi.advanceTimersByTimeAsync(10000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(closed).toEqual(["closed"]);
  });
});

describe("WsClient outcome frames", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hands the page the TurnOutcome inside the frame, not the frame itself", async () => {
    // The backend sends the contract's OutcomeMsg: {type: "outcome", outcome: {kind, ...}}.
    // Passing the whole frame left `kind` undefined, so the page dropped every greeting,
    // question and shortlist on production until 2026-09-17.
    const c = new WsClient("ws://x/ws");
    const seen: unknown[] = [];
    c.onOutcome = (o) => seen.push(o);
    const p = c.connect();
    FakeSocket.instances[0].serverOpens();
    await p;
    const outcome = { kind: "answered", spoken: "I found 3 listings.", view_model: { notices: [] } };
    FakeSocket.instances[0].onmessage?.({ data: JSON.stringify({ type: "outcome", outcome }) });
    expect(seen).toEqual([outcome]);
  });
});
