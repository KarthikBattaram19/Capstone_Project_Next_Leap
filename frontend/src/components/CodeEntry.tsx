"use client";

import { useState } from "react";

import { KeyIcon } from "./Icons";

/**
 * Cancel or move a visit by its 6-character code, for when the panel above is not
 * showing that booking (a reload, or a code from an earlier conversation). There
 * is no lookup route — the code is only ever presented with an action.
 *
 * The message shown for an unknown or cancelled code is whatever the API says,
 * verbatim — the two are identical by design (arch §10.2), and this component
 * must not tell them apart. A reschedule takes the new time as typed ("Tuesday
 * at 4 pm"); the service parses it in Asia/Kolkata.
 */
export function CodeEntry({
  onCancel,
  onReschedule,
  busy,
  message,
}: {
  onCancel?: (code: string) => void;
  onReschedule?: (code: string, when: string) => void;
  busy?: boolean;
  /** The API's `spoken` on success or its `detail` on an error, verbatim. */
  message?: string | null;
}) {
  const [code, setCode] = useState("");
  const [when, setWhen] = useState("");
  const ready = code.length === 6;
  return (
    <form
      className="code-entry"
      aria-label="Have a code?"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && when.trim()) onReschedule?.(code, when.trim());
      }}
    >
      <div className="code-entry__row">
        <KeyIcon className="code-entry__icon" />
        <span className="code-entry__label">Have a code?</span>
        <input
          className="input input--code"
          maxLength={6}
          placeholder="6-letter code"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/[^a-z0-9]/gi, "").toUpperCase())}
          aria-label="Visit code"
          spellCheck={false}
        />
        <button
          type="button"
          className="btn btn--ghost btn--sm btn--danger"
          disabled={!ready || busy || !onCancel}
          onClick={() => onCancel?.(code)}
        >
          {busy ? "Working…" : "Cancel visit"}
        </button>
      </div>
      <div className="code-entry__row">
        <input
          className="input"
          placeholder="New time, e.g. Tuesday at 4 pm"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
          aria-label="New visit time"
        />
        <button type="submit" className="btn btn--ghost btn--sm" disabled={!ready || !when.trim() || busy || !onReschedule}>
          {busy ? "Working…" : "Reschedule"}
        </button>
      </div>
      {message ? (
        <p className="code-entry__message" role="status">
          {message}
        </p>
      ) : null}
    </form>
  );
}
