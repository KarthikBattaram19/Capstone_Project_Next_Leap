export class MicCapture {
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private stream: MediaStream | null = null;
  private muted = false;

  async start(onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/worklets/capture-worklet.js");
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "capture-processor");
    this.node.port.onmessage = (e) => {
      const frame = e.data as ArrayBuffer;
      // While muted, send silence of the same length rather than nothing: Deepgram
      // closes a stream that goes quiet for ~10 s (net0001), and a steady stream of
      // zeros also lets its endpointing settle instead of freezing mid-utterance.
      onFrame(this.muted ? new ArrayBuffer(frame.byteLength) : frame);
    };
    // Not connected to destination: capture only, keeps running during playback.
    src.connect(this.node);
  }

  /**
   * Stop listening while the assistant is speaking. Seen on the deployed skeleton:
   * the reply came out of the speakers, the microphone heard it, Deepgram
   * transcribed it, and that started a new turn — which cancelled the reply that
   * was still playing. Three phantom turns in six seconds from room sound alone.
   * Barge-in (spec 6.15) is deliberately deferred to the orchestrator (Task 2.10):
   * it needs echo handling this skeleton does not have.
   */
  mute() {
    this.muted = true;
  }

  unmute() {
    this.muted = false;
  }

  async pause() {
    await this.ctx?.suspend();
  }

  async resume() {
    await this.ctx?.resume();
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
  }
}
