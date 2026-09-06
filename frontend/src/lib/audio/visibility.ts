import type { MicCapture } from "./capture";

/**
 * Backgrounded tab: pause capture, hold state, resume on return. Never treated as
 * end-of-speech (spec §6.16) — the backend hears silence stop, not a final.
 */
export function bindVisibility(mic: MicCapture): () => void {
  const h = () => {
    if (document.hidden) void mic.pause();
    else void mic.resume();
  };
  document.addEventListener("visibilitychange", h);
  return () => document.removeEventListener("visibilitychange", h);
}
