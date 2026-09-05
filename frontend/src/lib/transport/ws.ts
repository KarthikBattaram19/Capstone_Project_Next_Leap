export const CONTRACT_VERSION = "1";

export class ContractMismatchError extends Error {}

type AudioStart = { sample_rate: number; format: string };

export class WsClient {
  private ws: WebSocket | null = null;

  onTranscript: (text: string, final: boolean) => void = () => {};
  onAck: (text: string) => void = () => {};
  onAudioStart: (a: AudioStart) => void = () => {};
  onAudioChunk: (pcm: ArrayBuffer) => void = () => {};
  onAudioEnd: () => void = () => {};
  onAudioStop: () => void = () => {};
  onOutcome: (o: unknown) => void = () => {};
  onClosed: (reason: string) => void = () => {};

  constructor(private url: string) {}

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
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
        if (ev.code === 4400) reject(new ContractMismatchError(ev.reason));
        this.onClosed(ev.reason || `closed ${ev.code}`);
      };

      ws.onerror = () => reject(new Error("websocket error"));
    });
  }

  sendAudio(frame: ArrayBuffer) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(frame);
  }

  sendText(text: string) {
    this.ws?.send(JSON.stringify({ type: "text", text }));
  }

  close() {
    this.ws?.close();
  }
}
