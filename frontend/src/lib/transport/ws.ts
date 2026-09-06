export const CONTRACT_VERSION = "1";

export class ContractMismatchError extends Error {}

type AudioStart = { sample_rate: number; format: string };

const CLOSE_CONTRACT_MISMATCH = 4400;
/** Reconnect delays after an unexpected close (spec §6.A): then "unreachable". */
const BACKOFF_MS = [1000, 2000, 4000];

export class WsClient {
  private ws: WebSocket | null = null;
  private closedByUs = false;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;

  onTranscript: (text: string, final: boolean) => void = () => {};
  onAck: (text: string) => void = () => {};
  onAudioStart: (a: AudioStart) => void = () => {};
  onAudioChunk: (pcm: ArrayBuffer) => void = () => {};
  onAudioEnd: () => void = () => {};
  onAudioStop: () => void = () => {};
  onOutcome: (o: unknown) => void = () => {};
  /** Fired once per (re)connection after the hello handshake succeeds. */
  onOpen: () => void = () => {};
  /** Fired before each reconnect attempt, 1-based. */
  onReconnecting: (attempt: number) => void = () => {};
  /** "contract_version_mismatch" | "unreachable" | "closed <code>" | server reason. */
  onClosed: (reason: string) => void = () => {};

  constructor(private url: string) {}

  /**
   * Open the socket and complete the hello handshake. Resolves when any attempt
   * in the backoff ladder succeeds; rejects on a contract mismatch, or with
   * "unreachable" once the ladder is exhausted.
   */
  connect(): Promise<void> {
    this.closedByUs = false;
    this.attempt = 0;
    return new Promise((resolve, reject) => this.open(resolve, reject));
  }

  private open(resolve: () => void, reject: (e: Error) => void): void {
    {
      let settled = false;
      const ws = new WebSocket(this.url);
      ws.binaryType = "arraybuffer";
      this.ws = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "hello", contract_version: CONTRACT_VERSION }));
      };

      ws.onmessage = (ev) => {
        if (ev.data instanceof ArrayBuffer) {
          this.onAudioChunk(ev.data);
          return;
        }
        const m = JSON.parse(ev.data as string);
        switch (m.type) {
          case "hello":
            settled = true;
            this.attempt = 0;
            this.onOpen();
            resolve();
            break;
          case "transcript":
            this.onTranscript(m.text, m.final);
            break;
          case "ack":
            this.onAck(m.text);
            break;
          case "audio_out":
            if (m.event === "start") this.onAudioStart(m);
            else if (m.event === "end") this.onAudioEnd();
            else if (m.event === "stop") this.onAudioStop();
            break;
          case "outcome":
            this.onOutcome(m);
            break;
        }
      };

      ws.onclose = (ev) => {
        if (ev.code === CLOSE_CONTRACT_MISMATCH) {
          const reason = ev.reason || "contract_version_mismatch";
          if (!settled) reject(new ContractMismatchError(reason));
          this.onClosed(reason);
          return;
        }
        if (this.closedByUs) {
          this.onClosed(ev.reason || "closed");
          return;
        }
        // Unexpected close: back off and try again, then give up loudly. The
        // caller's promise stays pending across the ladder — the next attempt
        // inherits resolve/reject — so the page shows one "connecting", not a
        // flicker of "unreachable" followed by retries.
        if (this.attempt < BACKOFF_MS.length) {
          const delay = BACKOFF_MS[this.attempt++];
          this.onReconnecting(this.attempt);
          const settle = settled ? { resolve: () => {}, reject: () => {} } : { resolve, reject };
          this.timer = setTimeout(() => this.open(settle.resolve, settle.reject), delay);
          return;
        }
        if (!settled) reject(new Error("unreachable"));
        this.onClosed("unreachable");
      };

      ws.onerror = () => {
        /* onclose follows and carries the decision */
      };
    }
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  sendAudio(frame: ArrayBuffer) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(frame);
  }

  sendText(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "text", text }));
  }

  close() {
    this.closedByUs = true;
    clearTimeout(this.timer);
    this.ws?.close();
  }
}
