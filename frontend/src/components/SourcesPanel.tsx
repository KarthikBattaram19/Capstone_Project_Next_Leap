import type { CitationVM } from "@/lib/viewmodels/contract";

import { LinkIcon } from "./Icons";

/** Every citation with its full label — never a bare "[OSM]" — linked when a URL exists. */
export function SourcesPanel({ sources }: { sources: CitationVM[] }) {
  if (sources.length === 0) return null;
  return (
    <section className="sources" aria-label="Sources">
      <h2 className="sources__title">Sources</h2>
      <ol className="sources__list">
        {sources.map((s, i) => (
          <li key={s.ref} id={`src-${s.ref}`} className="sources__item">
            <span className="sources__num">{i + 1}</span>
            {s.url ? (
              <a className="sources__label sources__label--link" href={s.url} target="_blank" rel="noreferrer">
                {s.label}
                <LinkIcon className="sources__link-icon" />
              </a>
            ) : (
              <span className="sources__label">{s.label}</span>
            )}
            {s.method || s.as_of ? (
              <span className="sources__meta">
                {[s.method, s.timing, s.as_of].filter(Boolean).join(" · ")}
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
