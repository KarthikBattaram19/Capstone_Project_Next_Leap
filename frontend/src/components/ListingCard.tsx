import type { CardVM } from "@/lib/viewmodels/contract";
import { NOT_STATED } from "@/lib/viewmodels/contract";

import { CommuteRow } from "./CommuteRow";

/** A value cell: money and sizes get the numeric face; "not stated" is muted, never blank. */
function Field({ label, value, numeric }: { label: string; value: string; numeric?: boolean }) {
  const none = value === NOT_STATED;
  return (
    <div className="card__field">
      <span className="card__label">{label}</span>
      <span className={"card__value" + (numeric && !none ? " card__value--num" : "") + (none ? " card__value--none" : "")}>
        {value}
      </span>
    </div>
  );
}

export function ListingCard({
  card,
  selected,
  onWhy,
}: {
  card: CardVM;
  selected?: boolean;
  onWhy?: (card: CardVM) => void;
}) {
  return (
    <article
      className={"card" + (selected ? " card--selected" : "")}
      data-listing-id={card.listing_id}
      aria-label={`${card.locality}, ${card.society_name}`}
    >
      <header className="card__head">
        <div>
          <h3 className="card__title">{card.locality}</h3>
          <p className="card__society">{card.society_name}</p>
        </div>
        <div className="card__rent-block">
          <span className="card__rank">#{card.rank}</span>
          <span className={"card__rent" + (card.rent === NOT_STATED ? " card__value--none" : "")}>
            {card.rent}
            {card.rent !== NOT_STATED ? <span className="card__per"> / mo</span> : null}
          </span>
        </div>
      </header>

      <dl className="card__grid">
        <Field label="Deposit" value={card.deposit} numeric />
        <Field label="Maintenance" value={card.maintenance} numeric />
        <Field label="BHK" value={card.bhk_type} />
        <Field label="Size (sq ft)" value={card.square_footage} numeric />
        <Field label="Floor" value={card.floor} />
        <Field label="Parking" value={card.parking} />
        <Field label="Furnishing" value={card.furnishing} />
        <Field label="Available from" value={card.available_from} />
      </dl>

      <div className="card__amenities">
        {card.amenities.length === 0 ? (
          <span className="card__value--none">Amenities {NOT_STATED}</span>
        ) : (
          card.amenities.map((a) => (
            <span key={a} className="chip chip--amenity">
              {a}
            </span>
          ))
        )}
      </div>

      <ul className="card__commute">
        <CommuteRow row={card.transit} />
        {card.your_commute ? <CommuteRow row={card.your_commute} /> : null}
      </ul>

      {onWhy ? (
        <footer className="card__foot">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => onWhy(card)}>
            Why this one?
          </button>
        </footer>
      ) : null}
    </article>
  );
}
