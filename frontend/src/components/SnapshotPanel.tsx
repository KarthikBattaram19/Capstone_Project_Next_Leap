import type { ExplanationVM, SnapshotVM } from "@/lib/viewmodels/contract";

import { CalendarIcon } from "./Icons";

/**
 * "Why this one": the fact-led opener, then only the sentences that survived the
 * assembler, each with the citation chips it relies on. Gaps are named, never
 * hidden. Nothing here is computed — it is drawn as received (AD-5).
 */
export function SnapshotPanel({
  explanation,
  snapshot,
  onBook,
}: {
  explanation: ExplanationVM;
  snapshot?: SnapshotVM | null;
  onBook?: (listingId: string) => void;
}) {
  const refIndex = new Map(explanation.sources.map((s, i) => [s.ref, i + 1]));
  const gaps = explanation.gaps.length > 0 ? explanation.gaps : (snapshot?.gaps ?? []);
  return (
    <section className="why" aria-label="Why this one">
      <header className="why__head">
        <h2 className="why__title">Why this one</h2>
        {snapshot?.limited ? <span className="tag tag--muted">Limited neighbourhood data</span> : null}
      </header>

      <p className="why__opener">{explanation.opener}</p>

      {explanation.claims.length > 0 ? (
        <ol className="why__claims">
          {explanation.claims.map((c, i) => (
            <li key={i} className="why__claim">
              <span className="why__claim-text">{c.text}</span>
              {c.citation_refs.map((r) => (
                <a key={r} className="cite" href={`#src-${r}`} title={r}>
                  {refIndex.get(r) ?? "?"}
                </a>
              ))}
            </li>
          ))}
        </ol>
      ) : (
        <p className="why__none">No further explanation could be grounded for this listing.</p>
      )}

      {gaps.length > 0 ? (
        <div className="why__gaps">
          <span className="why__gaps-label">Gaps</span>
          <ul>
            {gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {onBook ? (
        <footer className="why__foot">
          <button type="button" className="btn btn--accent" onClick={() => onBook(explanation.listing_id)}>
            <CalendarIcon className="btn__icon" />
            Book a site visit
          </button>
        </footer>
      ) : null}
    </section>
  );
}
