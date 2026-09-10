/**
 * The browser's mirror of the conversation (arch §11, Task 3.5). Temporary, in
 * memory, gone on reload — the backend holds the real session.
 *
 * Two rules the tests pin, because the spec's failure list depends on them:
 *   - a `failed` outcome never clears the previous shortlist (spec §6.11);
 *   - "unreachable" is its own state, never rendered as an empty shortlist (§6.12).
 */
import type {
  BookingState,
  BookingVM,
  ExplanationVM,
  ShortlistVM,
  SlotVM,
  SnapshotVM,
  TurnOutcome,
  UnmetConstraint,
} from "@/lib/viewmodels/contract";

export type Connection = "connecting" | "open" | "closed" | "mismatch" | "unreachable";
export type Listening = "idle" | "listening" | "processing" | "speaking";

export interface SessionState {
  connection: Connection;
  listening: Listening;
  transcript: string;
  transcriptFinal: boolean;
  /** The last thing Nakshatra said, as text (every outcome is spoken and shown). */
  reply: string;
  readback: string[];
  shortlist: ShortlistVM | null;
  explanation: ExplanationVM | null;
  snapshot: SnapshotVM | null;
  booking: BookingVM | null;
  offeredSlots: SlotVM[];
  notices: string[];
  emptyResult: { unmet: UnmetConstraint[]; suggestions: string[]; spoken: string } | null;
  question: { question: string; field: string; options: string[] } | null;
  lastFailure: { capability: string; tell_renter: string; retry_worth_it: boolean } | null;
  degraded: { missing: string[]; why: string } | null;
  micError: "denied" | "no_device" | null;
  voiceOut: "on" | "blocked" | "unavailable";
}

export const initial: SessionState = {
  connection: "connecting",
  listening: "idle",
  transcript: "",
  transcriptFinal: false,
  reply: "",
  readback: [],
  shortlist: null,
  explanation: null,
  snapshot: null,
  booking: null,
  offeredSlots: [],
  notices: [],
  emptyResult: null,
  question: null,
  lastFailure: null,
  degraded: null,
  micError: null,
  voiceOut: "on",
};

export type Action =
  | { type: "open" }
  | { type: "closed"; reason: string }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "ack" }
  | { type: "speaking"; on: boolean }
  | { type: "outcome"; outcome: TurnOutcome }
  | { type: "mic_error"; error: "denied" | "no_device" | null }
  | { type: "voice_out"; state: SessionState["voiceOut"] }
  /** Slots fetched over HTTP (POST /bookings/slots) for a listing, or for a reschedule. */
  | { type: "offered"; slots: SlotVM[] }
  /** A booking returned by POST /bookings or /bookings/{code}/reschedule; the offer is over. */
  | { type: "booking"; booking: BookingVM }
  /** POST /bookings/{code}/cancel answered: the state the service now reports for that code. */
  | { type: "booking_state"; code: string; state: BookingState };

function closedConnection(reason: string): Connection {
  if (reason === "contract_version_mismatch") return "mismatch";
  if (reason === "unreachable") return "unreachable";
  if (reason === "reconnecting") return "connecting"; // the backoff ladder is running
  return "closed";
}

export function reduce(s: SessionState, a: Action): SessionState {
  switch (a.type) {
    case "open":
      return { ...s, connection: "open" };
    case "closed":
      return { ...s, connection: closedConnection(a.reason), listening: "idle" };
    case "transcript":
      return {
        ...s,
        transcript: a.text,
        transcriptFinal: a.final,
        listening: a.final ? s.listening : "listening",
      };
    case "ack":
      return { ...s, listening: "processing", question: null };
    case "speaking":
      return { ...s, listening: a.on ? "speaking" : "idle" };
    case "mic_error":
      return { ...s, micError: a.error };
    case "voice_out":
      return { ...s, voiceOut: a.state };
    case "offered":
      return { ...s, offeredSlots: a.slots };
    case "booking":
      return { ...s, booking: a.booking, offeredSlots: [] };
    case "booking_state":
      // Only the booking on screen changes; a code typed for some other visit does
      // not touch it. The shortlist and everything else stay as they were.
      if (!s.booking || s.booking.code !== a.code) return s;
      return { ...s, booking: { ...s.booking, state: a.state } };
    case "outcome": {
      const o = a.outcome;
      const base: SessionState = {
        ...s,
        listening: "idle",
        reply: o.spoken,
        question: null,
        lastFailure: null,
        degraded: null,
        emptyResult: null,
      };
      switch (o.kind) {
        case "answered":
        case "degraded": {
          const vm = o.view_model;
          return {
            ...base,
            readback: vm.constraints_readback ?? [],
            shortlist: vm.shortlist ?? s.shortlist,
            explanation: vm.explanation ?? null,
            snapshot: vm.snapshot ?? null,
            booking: vm.booking ?? s.booking,
            offeredSlots: vm.offered_slots ?? [],
            notices: vm.notices ?? [],
            degraded: o.kind === "degraded" ? { missing: o.missing, why: o.why } : null,
          };
        }
        case "empty":
          return {
            ...base,
            shortlist: null,
            explanation: null,
            emptyResult: { unmet: o.unmet, suggestions: o.suggestions, spoken: o.spoken },
          };
        case "failed":
          // The previous shortlist is carried over untouched through `base`.
          return {
            ...base,
            lastFailure: {
              capability: o.capability,
              tell_renter: o.tell_renter,
              retry_worth_it: o.retry_worth_it,
            },
          };
        case "needs_input":
          return {
            ...base,
            question: { question: o.question, field: o.field, options: o.options ?? [] },
          };
      }
      return s;
    }
  }
  return s;
}
