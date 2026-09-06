// Downsamples the AudioContext rate to 16 kHz mono PCM16 and posts 20 ms frames (320 samples).
//
// The AudioContext runs at the hardware rate — 48 kHz on most Windows machines — so
// this has to drop 2 of every 3 samples. Dropping them outright is aliasing: every
// frequency above 8 kHz folds back INTO the speech band as a phantom tone (a 12 kHz
// sibilant lands on top of 4 kHz). Speech is full of energy up there, so consonants
// smear and the transcript comes back with the wrong words. So low-pass first, then
// decimate — the filter is the part that makes the discarded samples discardable.
//
// Two cascaded 2nd-order Butterworth sections at 7 kHz (just under the 8 kHz Nyquist of
// the 16 kHz output), computed for the ACTUAL input rate rather than assumed to be
// 48 kHz. Measured on a 12 kHz tone at 48 kHz, which folds onto 4 kHz: the shipped
// naive decimation leaves the phantom at 0.500, one section cuts it to 0.118, two cut
// it to 0.028 (25 dB, an 18x reduction) while a 1 kHz speech tone comes through at
// 0.4998 against an unfiltered 0.5000 — the filter removes the fold, not the voice.
class Biquad {
  constructor(sampleRate, cutoff) {
    const w0 = (2 * Math.PI * cutoff) / sampleRate;
    const cos = Math.cos(w0);
    const alpha = Math.sin(w0) / Math.SQRT2; // Q = 1/sqrt(2), maximally flat
    const b0 = (1 - cos) / 2;
    const b1 = 1 - cos;
    const b2 = (1 - cos) / 2;
    const a0 = 1 + alpha;
    const a1 = -2 * cos;
    const a2 = 1 - alpha;
    this.b0 = b0 / a0;
    this.b1 = b1 / a0;
    this.b2 = b2 / a0;
    this.a1 = a1 / a0;
    this.a2 = a2 / a0;
    this.x1 = this.x2 = this.y1 = this.y2 = 0;
  }

  step(x) {
    const y = this.b0 * x + this.b1 * this.x1 + this.b2 * this.x2 - this.a1 * this.y1 - this.a2 * this.y2;
    this.x2 = this.x1;
    this.x1 = x;
    this.y2 = this.y1;
    this.y1 = y;
    return y;
  }
}

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = [];
    this.ratio = sampleRate / 16000;
    this.acc = 0;
    // Nothing to remove when the hardware already runs at or below 16 kHz.
    this.lp1 = this.ratio > 1 ? new Biquad(sampleRate, 7000) : null;
    this.lp2 = this.ratio > 1 ? new Biquad(sampleRate, 7000) : null;
  }

  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = this.lp1 ? this.lp2.step(this.lp1.step(ch[i])) : ch[i];
      this.acc += 1;
      if (this.acc >= this.ratio) {
        this.acc -= this.ratio;
        this.buf.push(s);
      }
      if (this.buf.length === 320) {
        const out = new Int16Array(320);
        for (let j = 0; j < 320; j++) {
          out[j] = Math.max(-1, Math.min(1, this.buf[j])) * 0x7fff;
        }
        this.port.postMessage(out.buffer, [out.buffer]);
        this.buf = [];
      }
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
