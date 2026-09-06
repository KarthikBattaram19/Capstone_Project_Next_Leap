"use client";

import { useState } from "react";

import { KeyIcon } from "./Icons";

/**
 * Look up a booking by its 6-character code. The message shown for an unknown
 * or cancelled code is whatever the API says, verbatim — the two are identical
 * by design (arch §10.2), and this component must not tell them apart.
 */
export function CodeEntry({
  onLookup,
  busy,
  message,
}: {
  onLookup?: (code: string) => void;
  busy?: boolean;
  message?: string | null;
}) {
  const [code, setCode] = useState("");
  const ready = code.length === 6;
  return (
    <form
      className="code-entry"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) onLookup?.(code.toUpperCase());
      }}
    >
      <KeyIcon className="code-entry__icon" />
      <span className="code-entry__label">Have a code?</span>
      <input
        className="input input--code"
        maxLength={6}
        placeholder="6 characters"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/[^a-z0-9]/gi, "").toUpperCase())}
        aria-label="Visit code"
        spellCheck={false}
      />
      <button type="submit" className="btn btn--ghost btn--sm" disabled={!ready || busy || !onLookup}>
        {busy ? "Looking…" : "Look up"}
      </button>
      {message ? <p className="code-entry__message">{message}</p> : null}
    </form>
  );
}
