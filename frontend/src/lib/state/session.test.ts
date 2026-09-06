import { describe, expect, it } from "vitest";

import { initial, reduce } from "./session";

const shortlist = {
  order: ["a"],
  groups: [{ locality: "Koramangala", count: 1, cards: [] }],
  unknown_on: [],
};

describe("session reducer", () => {
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

  it("transcript interim marks listening; final does not change the phase", () => {
    const s1 = reduce({ ...initial, listening: "idle" }, { type: "transcript", text: "two b", final: false });
    expect(s1.listening).toBe("listening");
    const s2 = reduce({ ...s1, listening: "speaking" }, { type: "transcript", text: "two bhk", final: true });
    expect(s2.listening).toBe("speaking");
    expect(s2.transcriptFinal).toBe(true);
  });
});
