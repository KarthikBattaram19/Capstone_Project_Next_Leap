import type { UnmetConstraint } from "@/lib/viewmodels/contract";

import { InfoIcon } from "./Icons";

/**
 * "Nothing matched" is a RESULT, not an error (arch §12.1). It uses only
 * `empty*` classes; FailureBanner uses only `failure*` classes, and a test
 * asserts the two never share one.
 */
export function EmptyState({
  result,
}: {
  result: { unmet: UnmetConstraint[]; suggestions: string[]; spoken: string };
}) {
  const binding = result.unmet.filter((u) => u.binding);
  const others = result.unmet.filter((u) => !u.binding);
  return (
    <section className="empty" role="status" aria-label="No listings matched">
      <div className="empty__head">
        <InfoIcon className="empty__icon" />
        <h2 className="empty__title">{result.spoken || "Nothing matched what you asked for."}</h2>
      </div>
      {binding.length > 0 ? (
        <p className="empty__binding">
          The requirement that excluded the most listings:{" "}
          {binding.map((u) => (
            <span key={u.field} className="empty__constraint">
              {u.field.replace(/_/g, " ")} {u.value}
            </span>
          ))}
        </p>
      ) : null}
      {others.length > 0 ? (
        <p className="empty__others">
          Also unmet:{" "}
          {others.map((u) => (
            <span key={u.field} className="empty__constraint">
              {u.field.replace(/_/g, " ")} {u.value}
            </span>
          ))}
        </p>
      ) : null}
      {result.suggestions.length > 0 ? (
        <ul className="empty__suggestions">
          {result.suggestions.map((s) => (
            <li key={s} className="empty__suggestion">
              {s}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="empty__promise">I won&apos;t relax anything myself — tell me what to change.</p>
    </section>
  );
}
