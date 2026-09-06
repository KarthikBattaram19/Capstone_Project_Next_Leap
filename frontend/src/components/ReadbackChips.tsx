import { CheckIcon } from "./Icons";

/** What Nakshatra understood, as the backend phrased it. Confirmed items carry a tick. */
export function ReadbackChips({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="readback" aria-label="What Nakshatra understood">
      {items.map((t) => (
        <li key={t} className="chip chip--readback">
          <CheckIcon className="chip__tick" />
          {t}
        </li>
      ))}
    </ul>
  );
}
