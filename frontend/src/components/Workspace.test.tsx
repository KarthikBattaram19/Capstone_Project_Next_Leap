import { fireEvent, render, screen } from "@testing-library/react";
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
