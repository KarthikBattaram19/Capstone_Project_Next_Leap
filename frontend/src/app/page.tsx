"use client";

import { useCallback, useEffect, useReducer, useRef, useState, useSyncExternalStore } from "react";

import { MicControl } from "@/components/MicControl";
import { type Service, StatusPill } from "@/components/StatusPill";
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
/** Marks a live conversation so a reload can say it was not saved (spec §6.21). */
function markLive(): void {
  try {
    sessionStorage.setItem("scout:live", "1");
  } catch {
    /* ignore */
  }
}

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

/**
 * Voice output is "unavailable" when an outcome arrived after an ack and no
 * `audio_out start` followed within this window (spec §6.53). The window opens
 * at the OUTCOME, not at the ack: the service speaks after it sends the outcome
 * (live.py: outcome, then the speaking task), and a turn may lawfully take up to
 * 3.5 s from ack to first audio (Gate L) — a timer from the ack would raise a
 * false alarm on most turns.
 */
const VOICE_TIMEOUT_MS = 2000;

/**
 * A reply that stops mid-stream: if no audio chunk arrives for this long after playback
 * began, give the microphone back and drop the "speaking" state. The backend bounds a
 * stalled sentence at 4-6 s (speaker.py); this is the page's own floor under it, because
 * a muted mic with nothing playing is a renter who can neither hear nor be heard.
 */
const AUDIO_STALL_MS = 8000;

/**
 * "Was this tab reloaded mid-conversation?" — read once when the page's code
 * loads in the browser (the flag is set while a session is live, and a reload is
 * the only way to arrive here with it still set), cleared when the session ends.
 */
const reloadFlag = (() => {
  let flag = false;
  try {
    if (typeof sessionStorage !== "undefined" && sessionStorage.getItem("scout:live") === "1") {
      sessionStorage.removeItem("scout:live");
      flag = true;
    }
  } catch {
    /* server render, private mode, or storage blocked */
  }
  const subs = new Set<() => void>();
  return {
    subscribe: (cb: () => void) => {
      subs.add(cb);
      return () => subs.delete(cb);
    },
    get: () => flag,
    getServer: () => false,
    clear: () => {
      flag = false;
      subs.forEach((cb) => cb());
    },
  };
})();

/** The API's `detail` verbatim (never our own wording); a plain sentence only when there is no response at all. */
function apiMessage(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

export default function Page() {
  const [s, dispatch] = useReducer(reduce, initial);
  const [started, setStarted] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [bookingBusy, setBookingBusy] = useState(false);
  const [bookingError, setBookingError] = useState<string | null>(null);
  const [bookingMessage, setBookingMessage] = useState<string | null>(null);
  const [codeMessage, setCodeMessage] = useState<string | null>(null);
  const [bookingListingId, setBookingListingId] = useState<string | null>(null);
  const [rescheduleCode, setRescheduleCode] = useState<string | null>(null);
  // A reload mid-conversation loses the conversation (spec §6.21); say so, on the
  // welcome screen and then in the workspace, until the renter ends the session.
  // The server snapshot is false, so the first paint matches and React re-renders
  // with the browser's answer after hydration — no skew, no setState in an effect.
  const reloaded = useSyncExternalStore(reloadFlag.subscribe, reloadFlag.get, reloadFlag.getServer);

  const ws = useRef<WsClient | null>(null);
  const mic = useRef<MicCapture | null>(null);
  const player = useRef<PcmPlayer | null>(null);
  const http = useRef(new HttpClient(API));
  // What the pill shows before a session: the backend's health, checked once on load.
  const [service, setService] = useState<Service>("checking");
  useEffect(() => {
    let live = true;
    http.current.health().then((ok) => {
      if (live) setService(ok ? "up" : "down");
    });
    return () => {
      live = false;
    };
  }, []);
  const unmuteTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const stallTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Set when the stream stalled: late chunks of that reply are dropped, not played.
  const stalled = useRef(false);
  const voiceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // True from an ack until `audio_out start`: the outcome then decides whether to wait for voice.
  const awaitingVoice = useRef(false);
  const unbindVisibility = useRef<(() => void) | null>(null);
  // True from the click until the mic is live, so a second click cannot open a
  // second session (two sockets into one player was full-scale noise, 2026-09-06).
  const starting = useRef(false);

  const stopSession = useCallback(() => {
    clearTimeout(unmuteTimer.current);
    clearTimeout(voiceTimer.current);
    awaitingVoice.current = false;
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
    dispatch({ type: "mic_error", error: null });
    // Whatever a previous attempt left behind goes first: never two sessions per page.
    stopSession();
    try {
      // Unlock audio inside the click, not after an await on the socket (spec §6.15).
      player.current ??= new PcmPlayer(24000);
      const unlocked = await player.current.unlock();
      dispatch({ type: "voice_out", state: unlocked ? "on" : "blocked" });

      const client = new WsClient(wsUrl());
      const armStallGuard = () => {
        clearTimeout(stallTimer.current);
        stallTimer.current = setTimeout(() => {
          stalled.current = true;
          player.current?.stop();
          clearTimeout(unmuteTimer.current);
          mic.current?.unmute();
          dispatch({ type: "speaking", on: false });
        }, AUDIO_STALL_MS + (player.current?.remainingMs() ?? 0));
      };
      client.onOpen = () => dispatch({ type: "open" });
      client.onReconnecting = () => dispatch({ type: "closed", reason: "reconnecting" });
      client.onTranscript = (text, final) => dispatch({ type: "transcript", text, final });
      client.onAck = () => {
        dispatch({ type: "ack" });
        clearTimeout(voiceTimer.current);
        awaitingVoice.current = true;
      };
      client.onAudioStart = (a) => {
        clearTimeout(voiceTimer.current);
        awaitingVoice.current = false;
        dispatch({ type: "voice_out", state: player.current?.unlocked ? "on" : "blocked" });
        dispatch({ type: "speaking", on: true });
        player.current?.setSampleRate(a.sample_rate);
        player.current?.beginStream();
        // Mute BEFORE the first chunk plays, so the reply never reaches Deepgram.
        clearTimeout(unmuteTimer.current);
        mic.current?.mute();
        stalled.current = false;
        armStallGuard();
      };
      client.onAudioChunk = (pcm) => {
        if (stalled.current) return;
        player.current?.enqueue(pcm);
        armStallGuard();
      };
      client.onAudioEnd = () => {
        clearTimeout(stallTimer.current);
        if (stalled.current) return;
        // Un-mute when playback finishes, not when the server stops sending.
        const wait = (player.current?.remainingMs() ?? 0) + 150;
        clearTimeout(unmuteTimer.current);
        unmuteTimer.current = setTimeout(() => {
          mic.current?.unmute();
          dispatch({ type: "speaking", on: false });
        }, wait);
      };
      // Barge-in: the renter spoke over the reply; stop playing at once.
      client.onAudioStop = () => {
        clearTimeout(stallTimer.current);
        player.current?.stop();
        clearTimeout(unmuteTimer.current);
        mic.current?.unmute();
        dispatch({ type: "speaking", on: false });
      };
      client.onOutcome = (o) => {
        // The Task 0.8 stub sends `{kind:"answered", view_model:{stub:true}}` — there is
        // nothing to draw until the orchestrator (Task 2.10) sends the real contract.
        if (!isContractOutcome(o)) return;
        dispatch({ type: "outcome", outcome: o });
        // The greeting arrives with no ack before it; only a turn that was
        // acknowledged and answered is owed a voice within the window.
        if (awaitingVoice.current) {
          clearTimeout(voiceTimer.current);
          voiceTimer.current = setTimeout(() => {
            if (awaitingVoice.current) dispatch({ type: "voice_out", state: "unavailable" });
          }, VOICE_TIMEOUT_MS);
        }
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
      markLive();
    } catch (e) {
      if (e instanceof ContractMismatchError) {
        dispatch({ type: "closed", reason: "contract_version_mismatch" });
        setStarted(true);
      } else if (e instanceof MicError) {
        // The socket is open; let the renter type instead (spec §6.13).
        dispatch({ type: "mic_error", error: e.kind });
        setStarted(ws.current !== null);
        if (ws.current !== null) markLive();
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
    reloadFlag.clear();
    setBookingListingId(null);
    setRescheduleCode(null);
    setBookingError(null);
    setBookingMessage(null);
    setCodeMessage(null);
  }, [stopSession]);

  useEffect(() => () => stopSession(), [stopSession]);

  const sendText = useCallback((text: string) => {
    ws.current?.sendText(text);
    dispatch({ type: "transcript", text, final: true });
  }, []);

  const onWhy = useCallback((card: CardVM) => sendText(`Why the ${ORDINAL[card.rank - 1] ?? card.rank} one?`), [sendText]);

  // ---- Booking over HTTP (contract: /bookings/slots, /bookings, /bookings/{code}/cancel|reschedule)

  /** "Book a site visit" on a listing → POST /bookings/slots → the next free hours. */
  const onBook = useCallback(async (listingId: string) => {
    setBookingListingId(listingId);
    setRescheduleCode(null);
    setBookingError(null);
    setBookingMessage(null);
    setBookingBusy(true);
    try {
      const r = await http.current.slots(listingId);
      dispatch({ type: "offered", slots: r.slots });
      setBookingMessage(r.spoken);
    } catch (e) {
      setBookingError(apiMessage(e, "Could not fetch slots."));
    } finally {
      setBookingBusy(false);
    }
  }, []);

  /** A slot and an email → POST /bookings. The session id comes from the hello frame. */
  const onConfirm = useCallback(
    async (slot: SlotVM, email: string) => {
      if (!bookingListingId) return;
      setBookingError(null);
      setBookingBusy(true);
      try {
        const r = await http.current.book({
          session_id: ws.current?.sessionId ?? "",
          listing_id: bookingListingId,
          slot_start_ist: slot.start_ist,
          email,
        });
        dispatch({ type: "booking", booking: r.booking });
        setBookingMessage(r.spoken);
      } catch (e) {
        setBookingError(apiMessage(e, "Could not confirm the booking."));
      } finally {
        setBookingBusy(false);
      }
    },
    [bookingListingId],
  );

  /** BookingPanel Cancel → POST /bookings/{code}/cancel; the answer shows in the panel. */
  const onCancel = useCallback(async (code: string) => {
    setBookingError(null);
    setBookingBusy(true);
    try {
      const r = await http.current.cancel(code);
      dispatch({ type: "booking_state", code: r.code, state: r.state });
      setRescheduleCode(null);
      setBookingMessage(r.spoken);
    } catch (e) {
      setBookingError(apiMessage(e, "Could not cancel."));
    } finally {
      setBookingBusy(false);
    }
  }, []);

  /** BookingPanel Reschedule → slots for the booking's listing, then the renter picks one. */
  const onReschedule = useCallback(
    async (code: string) => {
      const listingId = s.booking?.code === code ? s.booking.listing_id : null;
      if (!listingId) return;
      setBookingError(null);
      setBookingBusy(true);
      try {
        const r = await http.current.slots(listingId);
        dispatch({ type: "offered", slots: r.slots });
        setRescheduleCode(code);
        setBookingMessage(r.spoken);
      } catch (e) {
        setBookingError(apiMessage(e, "Could not fetch slots."));
      } finally {
        setBookingBusy(false);
      }
    },
    [s.booking],
  );

  /** The picked slot → POST /bookings/{code}/reschedule. */
  const onRescheduleTo = useCallback(async (code: string, slot: SlotVM) => {
    setBookingError(null);
    setBookingBusy(true);
    try {
      const r = await http.current.reschedule(code, slot.start_ist);
      dispatch({ type: "booking", booking: r.booking });
      setRescheduleCode(null);
      setBookingMessage(r.spoken);
    } catch (e) {
      setBookingError(apiMessage(e, "Could not move the visit."));
    } finally {
      setBookingBusy(false);
    }
  }, []);

  /** CodeEntry Cancel by code — the panel above may not be showing that booking. */
  const onCodeCancel = useCallback(async (code: string) => {
    setCodeMessage(null);
    setBookingBusy(true);
    try {
      const r = await http.current.cancel(code);
      dispatch({ type: "booking_state", code: r.code, state: r.state });
      setCodeMessage(r.spoken);
    } catch (e) {
      setCodeMessage(apiMessage(e, "Could not cancel."));
    } finally {
      setBookingBusy(false);
    }
  }, []);

  /** CodeEntry Reschedule by code with a typed time; the service parses the time in IST. */
  const onCodeReschedule = useCallback(async (code: string, when: string) => {
    setCodeMessage(null);
    setBookingBusy(true);
    try {
      const r = await http.current.reschedule(code, when);
      dispatch({ type: "booking", booking: r.booking });
      setRescheduleCode(null);
      setCodeMessage(r.spoken);
    } catch (e) {
      setCodeMessage(apiMessage(e, "Could not move the visit."));
    } finally {
      setBookingBusy(false);
    }
  }, []);

  const onEnableVoice = useCallback(async () => {
    const ok = (await player.current?.unlock()) ?? false;
    dispatch({ type: "voice_out", state: ok ? "on" : "blocked" });
  }, []);

  return (
    <div className="app">
      <div className="app__top">
        <StatusPill connection={s.connection} started={started || connecting} service={service} />
      </div>

      {!started ? (
        <div className="welcome">
          <MicControl
            phase={connecting ? "connecting" : "idle"}
            onStart={startSession}
            micError={s.micError}
            reloaded={reloaded}
          />
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
            onRescheduleTo,
            onCodeCancel,
            onCodeReschedule,
          }}
          x={{ bookingBusy, bookingError, bookingMessage, codeMessage, bookingListingId, rescheduleCode, reloaded }}
        />
      )}
    </div>
  );
}
