import type { CommuteRowVM } from "@/lib/viewmodels/contract";
import { NOT_STATED } from "@/lib/viewmodels/contract";

/**
 * One commute line: what · value · method badge. The badge is never dropped for
 * width — at narrow widths globals.css hides the VALUE, never the badge (spec §4).
 * The full label (source, method, date) rides on the `title` attribute.
 */
export function CommuteRow({ row }: { row: CommuteRowVM }) {
  const notStated = row.value_text === NOT_STATED;
  return (
    <li className="commute" title={row.full_label}>
      <span className="commute__what">{row.what}</span>
      <span className={"commute__value" + (notStated ? " commute__value--none" : "")}>
        {row.value_text}
      </span>
      {!notStated && row.badge ? (
        <span className={"badge " + (row.badge === "straight-line" ? "badge--straight" : "badge--route")}>
          {row.badge}
        </span>
      ) : null}
    </li>
  );
}
