// Downsamples the AudioContext rate to 16 kHz mono PCM16 and posts 20 ms frames (320 samples).
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = [];
    this.ratio = sampleRate / 16000;
    this.acc = 0;
  }

  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += 1;
      if (this.acc >= this.ratio) {
        this.acc -= this.ratio;
        this.buf.push(ch[i]);
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
