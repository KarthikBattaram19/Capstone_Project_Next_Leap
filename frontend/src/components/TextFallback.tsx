"use client";

import { useState } from "react";

import { SendIcon } from "./Icons";

/** Typed input for when the microphone is unavailable (spec §6.13). Sends a `text` frame. */
export function TextFallback({ onSend, disabled }: { onSend: (text: string) => void; disabled?: boolean }) {
  const [text, setText] = useState("");
  return (
    <form
      className="typed"
      onSubmit={(e) => {
        e.preventDefault();
        const t = text.trim();
        if (!t) return;
        onSend(t);
        setText("");
      }}
    >
      <input
        className="input"
        placeholder="Type instead…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
        aria-label="Type your request"
      />
      <button type="submit" className="btn btn--ghost btn--sm" disabled={disabled || !text.trim()} aria-label="Send">
        <SendIcon className="btn__icon" />
      </button>
    </form>
  );
}
