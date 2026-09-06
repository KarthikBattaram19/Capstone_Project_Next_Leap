import type { CardVM, ShortlistVM } from "@/lib/viewmodels/contract";

import { ListingCard } from "./ListingCard";

/**
 * Groups as the backend sent them, cards as the backend ordered them. This
 * component never sorts: the grouping is presentation and must not reorder the
 * shortlist (arch §8.2), and the edit suite asserts untouched cards come back
 * identical and in place.
 */
export function ShortlistCards({
  shortlist,
  selectedId,
  onWhy,
  onShowUnknown,
}: {
  shortlist: ShortlistVM;
  selectedId?: string | null;
  onWhy?: (card: CardVM) => void;
  onShowUnknown?: (field: string) => void;
}) {
  return (
    <div className="shortlist">
      {shortlist.groups.map((g) => (
        <section key={g.locality} className="group">
          <h2 className="group__title">
            {g.locality} <span className="group__count">· {g.count}</span>
          </h2>
          <div className="group__cards">
            {g.cards.map((c) => (
              <ListingCard
                key={c.listing_id}
                card={c}
                selected={selectedId === c.listing_id}
                onWhy={onWhy}
              />
            ))}
          </div>
        </section>
      ))}
      {shortlist.unknown_on.map((u) => (
        <div key={u.field} className="notice notice--unknown">
          <p>{u.spoken}</p>
          {onShowUnknown ? (
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => onShowUnknown(u.field)}>
              Show them
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
