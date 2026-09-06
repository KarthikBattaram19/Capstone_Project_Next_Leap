"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { MicControl } from "@/components/MicControl";
import { StatusPill } from "@/components/StatusPill";
import { Workspace } from "@/components/Workspace";
import { MicCapture, MicError } from "@/lib/audio/capture";
import { PcmPlayer } from "@/lib/audio/player";
import { bindVisibility } from "@/lib/audio/visibility";
import { initial, reduce } from "@/lib/state/session";
import { ApiError, HttpClient } from "@/lib/transport/http";
import { ContractMismatchError, WsClient } from "@/lib/transport/ws";
import type { CardVM, SlotVM, TurnOutcome } from "@/lib/viewmodels/contract";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** https://host -> wss://host/ws (and http -> ws for a local backend). */
function wsUrl(): string {
  return API.replace(/^https:/, "wss:").replace(/^http:/, "ws:") + "/ws";
}

const ORDINAL = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"];

/** True if this outcome has the shape Task 1.5 defines; the Task 0.8 stub's `{stub:true}` does not. */
function isContractOutcome(o: unknown): o is TurnOutcome {
  if (!o || typeof o !== "object") return false;
  const k = (o as { kind?: unknown }).kind;
  if (typeof k !== "string" || typeof (o as { spoken?: unknown }).spoken !== "string") return false;
  return ["answered", "empty", "degraded", "failed", "needs_input"].includes(k);
}

/** A 2 s window after an ack with no audio means voice output is unavailable (spec §6.53). */
const VOICE_TIMEOUT_MS = 2000;

export default function Page() {
  const [s, dispatch] = useReducer(reduce, initial);
  const [started, setStarted] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [bookingBusy, setBookingBusy] = useState(false);
  const [bookingError, setBookingError] = useState<string | null>(null);
  const [bookingListingId, setBookingListingId] = useState<string | null>(null);
  const [lookupMessage, setLookupMessage] = useState<string | null>(null);
  // A reload mid-conversation loses the conversation (spec §6.21); say so once.
  // Read lazily: the flag is only drawn after the mic click, so no hydration skew.
  const [reloaded, setReloaded] = useState(() => {
    try {
      const was = sessionStorage.getItem("scout:live") === "1";
      sessionStorage.removeItem("scout:live");
      return was;
    } catch {
      return false; // server render, or private mode
    }
  });

  const ws = useRef<WsClient | null>(null);
  const mic = useRef<MicCapture | null>(null);
  const player = useRef<PcmPlayer | null>(null);
  const http = useRef(new HttpClient(API));
  const unmuteTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const voiceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const unbindVisibility = useRef<(() => void) | null>(null);
  // True from the click until the mic is live, so a second click cannot open a
  // second session (two sockets into one player was full-scale noise, 2026-09-06).
  const starting = useRef(false);

  const stopSession = useCallback(() => {
    clearTimeout(unmuteTimer.current);
    clearTimeout(voiceTimer.current);
    unbindVisibility.current?.();
    unbindVisibility.current = null;
    mic.current?.stop();
    ws.current?.close();
    player.current?.stop();
    mic.current = null;
    ws.current = null;
    try {
      sessionStorage.removeItem("scout:live");
    } catch {
      /* ignore */
    }
  }, []);

  const startSession = useCallback(async () => {
    // Guarded by the in-flight flag only: "Try again" after an unreachable
    // service re-enters here with `started` already true, and must work.
    if (starting.current) return;
    starting.current = true;
    setConnecting(true);
    setReloaded(false);
    dispatch({ type: "mic_error", error: null });
    // Whatever a previous attempt left behind goes first: never two sessions per page.
    stopSession();
    try {
      // Unlock audio inside the click, not after an await on the socket (spec §6.15).
      player.current ??= new PcmPlayer(24000);
      const unlocked = await player.current.unlock();
      dispatch({ type: "voice_out", state: unlocked ? "on" : "blocked" });

      const client = new WsClient(wsUrl());
      client.onOpen = () => dispatch({ type: "open" });
      client.onReconnecting = () => dispatch({ type: "closed", reason: "reconnecting" });
      client.onTranscript = (text, final) => dispatch({ type: "transcript", text, final });
      client.onAck = () => {
        dispatch({ type: "ack" });
        clearTimeout(voiceTimer.current);
        voiceTimer.current = setTimeout(() => dispatch({ type: "voice_out", state: "unavailable" }), VOICE_TIMEOUT_MS);
      };
      client.onAudioStart = (a) => {
        clearTimeout(voiceTimer.current);
        dispatch({ type: "voice_out", state: player.current?.unlocked ? "on" : "blocked" });
        dispatch({ type: "speaking", on: true });
        player.current?.setSampleRate(a.sample_rate);
        player.current?.beginStream();
        // Mute BEFORE the first chunk plays, so the reply never reaches Deepgram.
        clearTimeout(unmuteTimer.current);
        mic.current?.mute();
      };
      client.onAudioChunk = (pcm) => player.current?.enqueue(pcm);
      client.onAudioEnd = () => {
        // Un-mute when playback finishes, not when the server stops sending.
        const wait = (player.current?.remainingMs() ?? 0) + 150;
        clearTimeout(unmuteTimer.current);
        unmuteTimer.current = setTimeout(() => {
          mic.current?.unmute();
          dispatch({ type: "speaking", on: false });
        }, wait);
      };
      client.onAudioStop = () => {
        player.current?.stop();
        clearTimeout(unmuteTimer.current);
        mic.current?.unmute();
        dispatch({ type: "speaking", on: false });
      };
      client.onOutcome = (o) => {
        if (isContractOutcome(o)) dispatch({ type: "outcome", outcome: o });
        // The Task 0.8 stub sends `{kind:"answered", view_model:{stub:true}}` — there is
        // nothing to draw until the orchestrator (Task 2.10) sends the real contract.
      };
      client.onClosed = (reason) => {
        dispatch({ type: "closed", reason });
      };

      await client.connect();
      ws.current = client;

      mic.current = new MicCapture();
      mic.current.onDeviceLost = () => dispatch({ type: "mic_error", error: "no_device" });
      await mic.current.start((frame) => client.sendAudio(frame));
      unbindVisibility.current = bindVisibility(mic.current);
      setStarted(true);
      try {
        sessionStorage.setItem("scout:live", "1");
      } catch {
        /* ignore */
      }
    } catch (e) {
      if (e instanceof ContractMismatchError) {
        dispatch({ type: "closed", reason: "contract_version_mismatch" });
        setStarted(true);
      } else if (e instanceof MicError) {
        // The socket is open; let the renter type instead (spec §6.13).
        dispatch({ type: "mic_error", error: e.kind });
        setStarted(ws.current !== null);
      } else {
        dispatch({ type: "closed", reason: "unreachable" });
        setStarted(true);
      }
    } finally {
      starting.current = false;
      setConnecting(false);
    }
  }, [stopSession]);

  const endSession = useCallback(() => {
    stopSession();
    setStarted(false);
    setBookingListingId(null);
    setLookupMessage(null);
  }, [stopSession]);

  useEffect(() => () => stopSession(), [stopSession]);

  const sendText = useCallback((text: string) => {
    ws.current?.sendText(text);
    dispatch({ type: "transcript", text, final: true });
  }, []);

  const onWhy = useCallback((card: CardVM) => sendText(`Why the ${ORDINAL[card.rank - 1] ?? card.rank} one?`), [sendText]);

  const onBook = useCallback(
    async (listingId: string) => {
      setBookingListingId(listingId);
      setBookingError(null);
      setBookingBusy(true);
      try {
        const r = await http.current.slots(listingId);
        dispatch({
          type: "outcome",
          outcome: {
            kind: "answered",
            spoken: "",
            view_model: { constraints_readback: s.readback, offered_slots: r.slots, notices: [] },
          },
        });
      } catch (e) {
        setBookingError(e instanceof ApiError ? e.message : "Could not fetch slots.");
      } finally {
        setBookingBusy(false);
      }
    },
    [s.readback],
  );

  const onConfirm = useCallback(
    async (slot: SlotVM, email: string) => {
      if (!bookingListingId) return;
      setBookingError(null);
      setBookingBusy(true);
      try {
        const r = await http.current.book({ session_id: "", listing_id: bookingListingId, slot_start_ist: slot.start_ist, email });
        dispatch({
          type: "outcome",
          outcome: { kind: "answered", spoken: r.spoken, view_model: { constraints_readback: s.readback, booking: r.booking } },
        });
      } catch (e) {
        setBookingError(e instanceof ApiError ? e.message : "Could not confirm the booking.");
      } finally {
        setBookingBusy(false);
      }
    },
    [bookingListingId, s.readback],
  );

  const onCancel = useCallback(async (code: string) => {
    setBookingBusy(true);
    try {
      const r = await http.current.cancel(code);
      setLookupMessage(r.spoken);
      sendText(`My visit ${code} is cancelled`);
    } catch (e) {
      setBookingError(e instanceof ApiError ? e.message : "Could not cancel.");
    } finally {
      setBookingBusy(false);
    }
  }, [sendText]);

  const onReschedule = useCallback((code: string) => sendText(`Reschedule my visit ${code}`), [sendText]);

  const onLookup = useCallback((code: string) => {
    setLookupMessage(null);
    sendText(`Look up my visit code ${code}`);
  }, [sendText]);

  const onEnableVoice = useCallback(async () => {
    const ok = (await player.current?.unlock()) ?? false;
    dispatch({ type: "voice_out", state: ok ? "on" : "blocked" });
  }, []);

  return (
    <div className="app">
      <div className="app__top">
        <StatusPill connection={s.connection} started={started || connecting} />
      </div>

      {!started ? (
        <div className="welcome">
          <MicControl phase={connecting ? "connecting" : "idle"} onStart={startSession} micError={s.micError} />
        </div>
      ) : (
        <Workspace
          s={s}
          h={{
            onEnd: endSession,
            onRetry: () => sendText(s.transcript),
            onReconnect: startSession,
            onSendText: sendText,
            onEnableVoice,
            onWhy,
            onBook,
            onConfirm,
            onCancel,
            onReschedule,
            onLookup,
          }}
          x={{ bookingBusy, bookingError, lookupMessage, bookingListingId, reloaded }}
        />
      )}
    </div>
  );
}
