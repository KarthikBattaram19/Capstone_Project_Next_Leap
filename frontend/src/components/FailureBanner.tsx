import { RetryIcon, WarnIcon } from "./Icons";

const NAMES: Record<string, string> = {
  speech_in: "speech recognition",
  understanding: "understanding",
  explanation: "explanation",
  speech_out: "voice output",
  calendar: "calendar",
  mail: "email",
};

/**
 * A capability is DOWN. This is an ERROR and looks nothing like EmptyState:
 * `failure*` classes only (arch §12.1, spec §6.11, §6.23).
 */
export function FailureBanner({
  failure,
  onRetry,
}: {
  failure: { capability: string; tell_renter: string; retry_worth_it: boolean };
  onRetry: () => void;
}) {
  const name = NAMES[failure.capability] ?? failure.capability;
  return (
    <section className="failure" role="alert">
      <WarnIcon className="failure__icon" />
      <div className="failure__body">
        <h2 className="failure__title">
          <span className="failure__cap">{name}</span> is unavailable right now
        </h2>
        <p className="failure__text">{failure.tell_renter}</p>
      </div>
      {failure.retry_worth_it ? (
        <button type="button" className="failure__retry" onClick={onRetry}>
          <RetryIcon className="failure__retry-icon" />
          Retry
        </button>
      ) : null}
    </section>
  );
}
