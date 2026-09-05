export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private nextAt = 0;
  private sources: AudioBufferSourceNode[] = [];

  constructor(private sampleRate: number) {}

  /** Must be called inside a user gesture (spec §6.15). */
  async unlock(): Promise<boolean> {
    this.ctx ??= new AudioContext({ sampleRate: this.sampleRate });
    try {
      await this.ctx.resume();
      return this.ctx.state === "running";
    } catch {
      return false;
    }
  }

  setSampleRate(rate: number) {
    if (rate !== this.sampleRate) {
      this.sampleRate = rate;
      this.ctx?.close();
      this.ctx = null;
    }
  }

  enqueue(pcm16: ArrayBuffer) {
    if (!this.ctx) return;
    const i16 = new Int16Array(pcm16);
    const buf = this.ctx.createBuffer(1, i16.length, this.sampleRate);
    const f32 = buf.getChannelData(0);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    const at = Math.max(this.ctx.currentTime, this.nextAt);
    src.start(at);
    this.nextAt = at + buf.duration;
    this.sources.push(src);
  }

  stop() {
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        // already stopped
      }
    }
    this.sources = [];
    this.nextAt = 0;
  }
}
