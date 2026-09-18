import { describe, expect, it } from "vitest";

import { initial, reduce } from "./session";

const shortlist = {
  order: ["a"],
  groups: [{ locality: "Koramangala", count: 1, cards: [] }],
  unknown_on: [],
};

describe("session reducer", () => {
  // Production, 2026-09-17: after "End conversation" a new session opened with the last
  // one's shortlist on screen, before the renter had said anything.
  it("a new conversation starts from a clean screen", () => {
    const slot = { start_ist: "2026-09-15T10:00:00+05:30", end_ist: "2026-09-15T11:00:00+05:30", spoken: "Mon 10 am" };
    let s = reduce(initial, {
      type: "outcome",
      outcome: {
        kind: "answered",
        spoken: "I found 1 listing.",
        view_model: { constraints_readback: ["in Koramangala"], shortlist, notices: ["x"] },
      },
    });
    s = reduce(s, { type: "offered", slots: [slot] });
    s = reduce(s, { type: "outcome", outcome: { kind: "needs_input", spoken: "", question: "Which?", field: "slot", options: ["a"] } });
    s = reduce(s, { type: "transcript", text: "the first one", final: true });

    const fresh = reduce(s, { type: "reset" });
    expect(fresh).toEqual(initial);

    // The greeting of the next session carries no shortlist and must not bring one back.
    const greeted = reduce(fresh, {
      type: "outcome",
      outcome: { kind: "answered", spoken: "Hello", view_model: { constraints_readback: [], shortlist: null, notices: [] } },
    });
    expect(greeted.shortlist).toBeNull();
    expect(greeted.offeredSlots).toEqual([]);
  });

  it("a failed outcome keeps the last shortlist on screen", () => {
    const s1 = reduce(initial, {
      type: "outcome",
      outcome: {
        kind: "answered",
        spoken: "",
        view_model: { constraints_readback: [], shortlist, notices: [] },
      },
    });
    const s2 = reduce(s1, {
      type: "outcome",
      outcome: {
        kind: "failed",
        capability: "understanding",
        tell_renter: "x",
        retry_worth_it: true,
        spoken: "x",
      },
    });
    expect(s2.shortlist).toEqual(shortlist);
    expect(s2.lastFailure?.capability).toBe("understanding");
  });

  it("unreachable backend is its own state, not an empty result", () => {
    const s = reduce(initial, { type: "closed", reason: "unreachable" });
    expect(s.connection).toBe("unreachable");
    expect(s.shortlist).toBeNull();
    expect(s.emptyResult).toBeNull();
  });

  it("a reconnect in progress shows as connecting, not as disconnected", () => {
    const s = reduce({ ...initial, connection: "open" }, { type: "closed", reason: "reconnecting" });
    expect(s.connection).toBe("connecting");
  });

  it("contract mismatch names itself", () => {
    expect(reduce(initial, { type: "closed", reason: "contract_version_mismatch" }).connection).toBe(
      "mismatch",
    );
  });

  it("an empty result clears the shortlist and carries the binding constraint", () => {
    const s1 = reduce(initial, {
      type: "outcome",
      outcome: {
        kind: "answered",
        spoken: "",
        view_model: { constraints_readback: [], shortlist, notices: [] },
      },
    });
    const s2 = reduce(s1, {
      type: "outcome",
      outcome: {
        kind: "empty",
        spoken: "Nothing under ₹25,000 in Koramangala.",
        unmet: [{ field: "rent_max", value: "25000", binding: true }],
        suggestions: ["try ₹30,000"],
      },
    });
    expect(s2.shortlist).toBeNull();
    expect(s2.emptyResult?.unmet[0].binding).toBe(true);
    expect(s2.lastFailure).toBeNull();
  });

  it("a question replaces any earlier question and an ack clears it", () => {
    const s1 = reduce(initial, {
      type: "outcome",
      outcome: { kind: "needs_input", spoken: "", question: "Which?", field: "rent_max", options: [] },
    });
    expect(s1.question?.question).toBe("Which?");
    const s2 = reduce(s1, { type: "ack" });
    expect(s2.question).toBeNull();
    expect(s2.listening).toBe("processing");
  });

  it("an HTTP booking replaces the offer, and a cancel by code changes only that booking", () => {
    const slot = { start_ist: "2026-09-15T10:00:00+05:30", end_ist: "2026-09-15T11:00:00+05:30", spoken: "Mon 10 am" };
    const s1 = reduce(
      { ...initial, shortlist },
      { type: "offered", slots: [slot] },
    );
    expect(s1.offeredSlots).toEqual([slot]);
    const booking = {
      code: "K7M4PX",
      listing_id: "a",
      slot,
      state: "booked" as const,
      pdf_status: "pending" as const,
      calendar_sync: "complete" as const,
    };
    const s2 = reduce(s1, { type: "booking", booking });
    expect(s2.booking).toEqual(booking);
    expect(s2.offeredSlots).toEqual([]);
    expect(s2.shortlist).toEqual(shortlist);
    // A different code leaves the booking on screen alone.
    const s3 = reduce(s2, { type: "booking_state", code: "ZZZZZZ", state: "cancelled" });
    expect(s3.booking?.state).toBe("booked");
    const s4 = reduce(s3, { type: "booking_state", code: "K7M4PX", state: "cancelled" });
    expect(s4.booking?.state).toBe("cancelled");
    expect(s4.shortlist).toEqual(shortlist);
  });

  it("what happened to the email updates only the booking with that code (spec §6.7)", () => {
    const slot = { start_ist: "2026-09-15T10:00:00+05:30", end_ist: "2026-09-15T11:00:00+05:30", spoken: "Mon 10 am" };
    const booking = {
      code: "K7M4PX",
      listing_id: "a",
      slot,
      state: "booked" as const,
      pdf_status: "pending" as const,
      calendar_sync: "complete" as const,
    };
    const s1 = reduce({ ...initial, shortlist, booking }, { type: "booking_pdf", code: "ZZZZZZ", pdf_status: "failed" });
    expect(s1.booking?.pdf_status).toBe("pending");
    const s2 = reduce(s1, { type: "booking_pdf", code: "K7M4PX", pdf_status: "failed" });
    expect(s2.booking?.pdf_status).toBe("failed");
    expect(s2.booking?.state).toBe("booked");
    expect(s2.shortlist).toEqual(shortlist);
  });

  // Production, 2026-09-18: on a "why this one?" turn the opener is spoken while Job 2 is
  // still writing, so the outcome lands mid-reply. Going idle there took the Stop control
  // off screen while the renter could still hear her — their only way to interrupt.
  it("an outcome that lands while she is speaking does not end the speaking phase", () => {
    const answered = { kind: "answered" as const, spoken: "Because it is a 2 BHK.", view_model: {} };
    const mid = reduce({ ...initial, listening: "speaking" }, { type: "outcome", outcome: answered });
    expect(mid.listening).toBe("speaking");
    // Playback says when she has stopped, not the outcome.
    expect(reduce(mid, { type: "speaking", on: false }).listening).toBe("idle");
    // A turn answered before any audio still lands the screen back at idle.
    const quiet = reduce({ ...initial, listening: "processing" }, { type: "outcome", outcome: answered });
    expect(quiet.listening).toBe("idle");
  });

  it("transcript interim marks listening; final does not change the phase", () => {
    const s1 = reduce({ ...initial, listening: "idle" }, { type: "transcript", text: "two b", final: false });
    expect(s1.listening).toBe("listening");
    const s2 = reduce({ ...s1, listening: "speaking" }, { type: "transcript", text: "two bhk", final: true });
    expect(s2.listening).toBe("speaking");
    expect(s2.transcriptFinal).toBe(true);
  });
});
