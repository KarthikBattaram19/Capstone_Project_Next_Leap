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

  async function startMic() {
    setError("");
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
      client.onAudioStart = (a) => player.current?.setSampleRate(a.sample_rate);
      client.onAudioChunk = (pcm) => player.current?.enqueue(pcm);
      client.onAudioStop = () => player.current?.stop();
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
    }
  }

  function stopMic() {
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
        style={{ padding: "12px 20px", fontSize: 16, cursor: "pointer" }}
      >
        {live ? "Stop" : "Start microphone"}
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
