import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { initial, type Listening } from "@/lib/state/session";

import { Workspace, type WorkspaceHandlers } from "./Workspace";

function handlers(over: Partial<WorkspaceHandlers> = {}): WorkspaceHandlers {
  const noop = () => {};
  return {
    onEnd: noop,
    onRetry: noop,
    onReconnect: noop,
    onSendText: noop,
    onStopSpeaking: noop,
    onEnableVoice: noop,
    onWhy: noop,
    onBook: noop,
    onConfirm: noop,
    onCancel: noop,
    onReschedule: noop,
    onRescheduleTo: noop,
    onCodeCancel: noop,
    onCodeReschedule: noop,
    onEmailPdf: noop,
    ...over,
  };
}

const at = (listening: Listening) => ({ ...initial, connection: "open" as const, listening });

const endButton = () => screen.getByRole("button", { name: /End conversation/ });

/** Where a control sits in its column: the thing a thumb aims at. */
function seat(el: HTMLElement) {
  const parent = el.parentElement!;
  return { column: parent.className, index: Array.prototype.indexOf.call(parent.children, el) };
}

describe("the Stop control (D2, 2026-09-17)", () => {
  // The mic is muted for the whole reply, so the renter could not interrupt a 57 s answer
  // by voice: "I don't know why you did not listen to me when I asked you to stop".
  it("is visible while Nakshatra is speaking and stops her when tapped", () => {
    const onStopSpeaking = vi.fn();
    render(<Workspace s={at("speaking")} h={handlers({ onStopSpeaking })} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop speaking" }));
    expect(onStopSpeaking).toHaveBeenCalledTimes(1);
  });

  it.each<Listening>(["idle", "listening", "processing"])("is not shown while %s", (state) => {
    render(<Workspace s={at(state)} h={handlers()} />);
    expect(screen.queryByRole("button", { name: "Stop speaking" })).toBeNull();
  });
});

/**
 * Production, 2026-09-18: "While I was giving my options, she suddenly took the
 * conversation to the beginning." "Stop speaking" existed only while she spoke and
 * "End conversation" sat directly below it, so the moment she stopped the Stop button
 * unmounted and End jumped up into its seat — a tap aimed at Stop that landed late
 * ended the conversation.
 */
describe("a late tap aimed at Stop must not end the conversation", () => {
  it("leaves End conversation in the same seat whether or not she is speaking", () => {
    render(<Workspace s={at("speaking")} h={handlers()} />);
    const whileSpeaking = seat(endButton());
    cleanup();
    render(<Workspace s={at("idle")} h={handlers()} />);
    expect(seat(endButton())).toEqual(whileSpeaking);
  });

  it("does not end the conversation on a single click", () => {
    const onEnd = vi.fn();
    render(<Workspace s={at("speaking")} h={handlers({ onEnd })} />);
    fireEvent.click(endButton());
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("does not end it on a double click either — the second click lands on End again", () => {
    const onEnd = vi.fn();
    render(<Workspace s={at("speaking")} h={handlers({ onEnd })} />);
    const before = seat(endButton());
    fireEvent.click(endButton());
    expect(seat(endButton())).toEqual(before); // nothing moved under the thumb
    fireEvent.click(endButton());
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("ends it for someone who means it, in two clicks", () => {
    const onEnd = vi.fn();
    render(<Workspace s={at("speaking")} h={handlers({ onEnd })} />);
    fireEvent.click(endButton());
    fireEvent.click(screen.getByRole("button", { name: "Yes, end it" }));
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("goes back to the conversation on Keep talking", () => {
    const onEnd = vi.fn();
    render(<Workspace s={at("speaking")} h={handlers({ onEnd })} />);
    fireEvent.click(endButton());
    fireEvent.click(screen.getByRole("button", { name: "Keep talking" }));
    expect(screen.queryByRole("button", { name: "Yes, end it" })).toBeNull();
    expect(onEnd).not.toHaveBeenCalled();
  });
});
