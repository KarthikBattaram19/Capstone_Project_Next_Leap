export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private nextAt = 0;
  private sources: AudioBufferSourceNode[] = [];
  /** Trailing byte of a chunk that ended mid-sample; belongs to the next chunk. */
  private carry: Uint8Array | null = null;

  constructor(private sampleRate: number) {}

  /** True while the browser lets this context play sound. */
  get unlocked(): boolean {
    return this.ctx?.state === "running";
  }

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

  /** A new utterance begins: a half sample left over from the last one must not be
   *  glued to its front, or every sample that follows is read a byte out of phase. */
  beginStream() {
    this.carry = null;
  }

  enqueue(pcm16: ArrayBuffer) {
    if (!this.ctx) return;

    // A PCM16 sample is two bytes, but the TTS stream does not chunk on sample
    // boundaries — real chunk sizes seen from Smallest.ai: 14481, 10849, 16384…
    // Converting each chunk on its own would throw on an odd length and, worse,
    // shift every later chunk by one byte, swapping the high and low half of every
    // sample. That is audible as loud noise, not as silence. So carry the odd
    // trailing byte over to the next chunk.
    let bytes = new Uint8Array(pcm16);
    if (this.carry) {
      const merged = new Uint8Array(this.carry.length + bytes.length);
      merged.set(this.carry, 0);
      merged.set(bytes, this.carry.length);
      bytes = merged;
      this.carry = null;
    }
    const usable = bytes.length - (bytes.length % 2);
    if (usable < bytes.length) this.carry = bytes.slice(usable);
    if (usable === 0) return;

    // DataView, not Int16Array: it has no byte-alignment requirement, and it lets
    // the little-endian read be explicit rather than inherited from the platform.
    const view = new DataView(bytes.buffer, bytes.byteOffset, usable);
    const samples = usable / 2;
    const buf = this.ctx.createBuffer(1, samples, this.sampleRate);
    const f32 = buf.getChannelData(0);
    for (let i = 0; i < samples; i++) f32[i] = view.getInt16(i * 2, true) / 0x8000;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    const at = Math.max(this.ctx.currentTime, this.nextAt);
    src.start(at);
    this.nextAt = at + buf.duration;
    this.sources.push(src);
  }

  /**
   * Milliseconds until the last queued buffer finishes. `audio_out end` means the
   * server has finished SENDING, not that the browser has finished PLAYING — chunks
   * arrive in a burst and are scheduled back to back, so several seconds of speech
   * can still be queued when the end marker lands.
   */
  remainingMs(): number {
    if (!this.ctx) return 0;
    return Math.max(0, this.nextAt - this.ctx.currentTime) * 1000;
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
    // A half sample left over from the interrupted utterance must not be glued to
    // the front of the next one.
    this.carry = null;
  }
}
