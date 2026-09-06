import { InfoIcon, RetryIcon } from "./Icons";

/** Shortlist shown, explanation withheld (Degraded). A result with a named hole. */
export function DegradedNotice({ degraded }: { degraded: { missing: string[]; why: string } }) {
  return (
    <p className="degraded" role="status">
      <InfoIcon className="degraded__icon" />
      <span>
        {degraded.missing.length > 0 ? <b>{degraded.missing.join(", ")} withheld</b> : <b>Partial answer</b>} — {degraded.why}
      </span>
    </p>
  );
}

/** The service cannot be reached at all. Its own state, never an empty shortlist (spec §6.12). */
export function UnreachablePanel({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="conn conn--unreachable" role="alert">
      <h2 className="conn__title">Can&apos;t reach the service</h2>
      <p className="conn__text">
        The connection dropped and three reconnect attempts failed. Anything shown below is what you last saw, and a
        confirmed booking still works with its code.
      </p>
      <button type="button" className="btn btn--accent" onClick={onRetry}>
        <RetryIcon className="btn__icon" />
        Try again
      </button>
    </section>
  );
}

/** The page was built against a different contract version than the service now speaks. */
export function MismatchPanel() {
  return (
    <section className="conn conn--mismatch" role="alert">
      <h2 className="conn__title">This page is out of date with the service</h2>
      <p className="conn__text">Reload to get the current version.</p>
      <button type="button" className="btn btn--accent" onClick={() => window.location.reload()}>
        Reload
      </button>
    </section>
  );
}

/** A note the backend asked us to show (e.g. a listing was withdrawn mid-flow). */
export function NoticeList({ notices }: { notices: string[] }) {
  if (notices.length === 0) return null;
  return (
    <ul className="notices">
      {notices.map((n) => (
        <li key={n} className="notice">
          {n}
        </li>
      ))}
    </ul>
  );
}

/** Audio is blocked by the browser until the renter clicks something (spec §6.15). */
export function VoiceOutNotice({ state, onEnable }: { state: "blocked" | "unavailable"; onEnable: () => void }) {
  if (state === "blocked") {
    return (
      <div className="toast toast--voice" role="status">
        <span>Sound is blocked by the browser.</span>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onEnable}>
          Enable voice
        </button>
      </div>
    );
  }
  return (
    <div className="toast toast--voice" role="status">
      Voice output is temporarily unavailable — replies are shown as text.
    </div>
  );
}

export function ReloadNotice() {
  return (
    <p className="reload-note" role="status">
      Your conversation was not saved; a confirmed booking still works with its code.
    </p>
  );
}
