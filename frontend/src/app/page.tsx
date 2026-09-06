"use client";

import { useRef, useState } from "react";

import { MicCapture } from "@/lib/audio/capture";
import { PcmPlayer } from "@/lib/audio/player";
import { ContractMismatchError, WsClient } from "@/lib/transport/ws";

/** https://host -> wss://host/ws (and http -> ws for a local backend). */
function wsUrl(): string {
  const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return api.replace(/^https:/, "wss:").replace(/^http:/, "ws:") + "/ws";
}

export default function Page() {
  const [live, setLive] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [ack, setAck] = useState("");
  const [outcome, setOutcome] = useState("");
  const [error, setError] = useState("");

  const ws = useRef<WsClient | null>(null);
  const mic = useRef<MicCapture | null>(null);
  const player = useRef<PcmPlayer | null>(null);
  const unmuteTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // True from the click until the mic is live. The setup below awaits the audio
  // unlock, the socket, the worklet and the permission prompt — a second or more —
  // and the button still read "Start microphone" throughout, so a second click ran
  // startMic again: two sockets, two Deepgram streams, two microphones, and both
  // sessions' TTS streams feeding ONE player. Interleaved chunks put every sample a
  // byte out of phase, which is full-scale noise. Seen on production 2026-09-06:
  // every utterance answered twice, 60 ms apart.
  const starting = useRef(false);
  const [connecting, setConnecting] = useState(false);

  async function startMic() {
    if (starting.current || live) return;
    starting.current = true;
    setConnecting(true);
    setError("");
    // Whatever a previous attempt left behind goes first, so there is never more
    // than one session per page.
    mic.current?.stop();
    ws.current?.close();
    mic.current = null;
    ws.current = null;
    try {
      // Unlock audio first: this must happen inside the click, not after an await
      // on the socket, or the browser refuses to play (spec §6.15).
      player.current ??= new PcmPlayer(24000);
      await player.current.unlock();

      const client = new WsClient(wsUrl());
      client.onTranscript = (text, final) => {
        setTranscript(text);
        if (final) setAck("");
      };
      client.onAck = (text) => setAck(`heard: ${text}`);
      client.onAudioStart = (a) => {
        player.current?.setSampleRate(a.sample_rate);
        player.current?.beginStream();
        // Mute BEFORE the first chunk plays, so the reply never reaches Deepgram.
        clearTimeout(unmuteTimer.current);
        mic.current?.mute();
      };
      client.onAudioChunk = (pcm) => player.current?.enqueue(pcm);
      client.onAudioEnd = () => {
        // Un-mute when playback finishes, not when the server stops sending: the
        // queue can still hold seconds of speech at this point. 150 ms of margin
        // covers the speaker-to-microphone tail.
        const wait = (player.current?.remainingMs() ?? 0) + 150;
        clearTimeout(unmuteTimer.current);
        unmuteTimer.current = setTimeout(() => mic.current?.unmute(), wait);
      };
      client.onAudioStop = () => {
        player.current?.stop();
        clearTimeout(unmuteTimer.current);
        mic.current?.unmute(); // nothing is playing any more
      };
      client.onOutcome = (o) => setOutcome(JSON.stringify(o, null, 2));
      client.onClosed = (reason) => {
        setLive(false);
        setError(`connection closed — ${reason}`);
      };

      await client.connect();
      ws.current = client;

      mic.current = new MicCapture();
      await mic.current.start((frame) => client.sendAudio(frame));
      setLive(true);
    } catch (e) {
      setLive(false);
      if (e instanceof ContractMismatchError) {
        setError("This page is out of date with the backend. Reload to get the current version.");
      } else if (e instanceof DOMException && e.name === "NotAllowedError") {
        setError("Microphone permission was denied. Allow it in the browser, then try again.");
      } else {
        setError(e instanceof Error ? e.message : "could not start");
      }
    } finally {
      starting.current = false;
      setConnecting(false);
    }
  }

  function stopMic() {
    clearTimeout(unmuteTimer.current);
    mic.current?.stop();
    ws.current?.close();
    player.current?.stop();
    setLive(false);
  }

  return (
    <main style={{ fontFamily: "system-ui", padding: 32, maxWidth: 720, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20 }}>Scout — walking skeleton</h1>
      <p style={{ color: "#666", fontSize: 14 }}>
        Task 0.9. One button, one transcript line. Not the product UI.
      </p>

      <button
        onClick={live ? stopMic : startMic}
        disabled={connecting}
        style={{ padding: "12px 20px", fontSize: 16, cursor: connecting ? "wait" : "pointer" }}
      >
        {live ? "Stop" : connecting ? "Connecting…" : "Start microphone"}
      </button>

      {error && (
        <p role="alert" style={{ color: "#b00", marginTop: 16 }}>
          {error}
        </p>
      )}

      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 14, color: "#666" }}>Transcript</h2>
        <p style={{ minHeight: 24 }}>{transcript || <em style={{ color: "#999" }}>—</em>}</p>
        <p style={{ color: "#0a0", minHeight: 24 }}>{ack}</p>
      </section>

      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 14, color: "#666" }}>Outcome</h2>
        <pre style={{ background: "#f5f5f5", padding: 12, overflowX: "auto", fontSize: 12 }}>
          {outcome || "—"}
        </pre>
      </section>
    </main>
  );
}
