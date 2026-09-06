"use client";

import { useState } from "react";

import type { BookingVM, SlotVM } from "@/lib/viewmodels/contract";

import { CalendarIcon, CheckIcon } from "./Icons";

const PDF_TEXT: Record<string, string> = {
  pending: "PDF on its way to your email",
  sent: "PDF sent to your email",
  failed: "The PDF could not be emailed — your code still works",
  not_applicable: "",
};

/** The email, echoed letter by letter — the highest-error input in the system (arch §10.3). */
function Echo({ value }: { value: string }) {
  if (!value) return null;
  return (
    <p className="booking__echo" aria-label="Email read back letter by letter">
      {Array.from(value).join(" · ")}
    </p>
  );
}

export function BookingPanel({
  booking,
  offeredSlots,
  listingLabel,
  busy,
  error,
  onConfirm,
  onCancel,
  onReschedule,
}: {
  booking: BookingVM | null;
  offeredSlots: SlotVM[];
  listingLabel?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm?: (slot: SlotVM, email: string) => void;
  onCancel?: (code: string) => void;
  onReschedule?: (code: string) => void;
}) {
  const [slot, setSlot] = useState<SlotVM | null>(offeredSlots[0] ?? null);
  const [email, setEmail] = useState("");

  const confirmed = booking && booking.state === "booked";

  return (
    <section className="booking" aria-label="Book a visit">
      <header className="booking__head">
        <div>
          <span className="booking__eyebrow">Site visit</span>
          <h2 className="booking__title">{confirmed ? "Visit booked" : "Book a visit"}</h2>
          {listingLabel ? <p className="booking__listing">{listingLabel}</p> : null}
        </div>
        <CalendarIcon className="booking__glyph" />
      </header>

      {!confirmed && offeredSlots.length > 0 ? (
        <>
          <div className="booking__slots" role="radiogroup" aria-label="Available visit slots">
            {offeredSlots.map((s) => {
              const on = slot?.start_ist === s.start_ist;
              return (
                <button
                  key={s.start_ist}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  className={"slot" + (on ? " slot--on" : "")}
                  onClick={() => setSlot(s)}
                >
                  <span className="slot__dot">{on ? <CheckIcon className="slot__check" /> : null}</span>
                  <span className="slot__time">{s.spoken}</span>
                </button>
              );
            })}
          </div>

          <label className="booking__field">
            <span className="booking__label">Your email for the confirmation PDF</span>
            <input
              className="input"
              type="email"
              autoComplete="email"
              placeholder="name@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <Echo value={email} />

          {error ? <p className="booking__error">{error}</p> : null}

          <button
            type="button"
            className="btn btn--accent btn--wide"
            disabled={!slot || !email || busy || !onConfirm}
            onClick={() => slot && onConfirm?.(slot, email)}
          >
            {busy ? "Confirming…" : "Confirm this visit"}
          </button>
        </>
      ) : null}

      {!confirmed && offeredSlots.length === 0 ? (
        <p className="booking__hint">
          Say <em>“book a visit”</em> for a listing and I will read out the next three free hours.
        </p>
      ) : null}

      {booking ? (
        <div className={"booking__confirmed" + (booking.state === "booked" ? "" : " booking__confirmed--off")}>
          <span className="booking__code-label">Your visit code</span>
          <div className="booking__code" aria-label={`Visit code ${Array.from(booking.code).join(" ")}`}>
            {booking.code}
          </div>
          <p className="booking__when">{booking.slot.spoken}</p>
          <ul className="booking__status">
            {booking.state !== "booked" ? <li className="booking__state">This booking is {booking.state}.</li> : null}
            {booking.state === "booked" && PDF_TEXT[booking.pdf_status] ? (
              <li className={"booking__pdf booking__pdf--" + booking.pdf_status}>
                {booking.pdf_status === "sent" ? <CheckIcon className="booking__tick" /> : null}
                {PDF_TEXT[booking.pdf_status]}
              </li>
            ) : null}
            {booking.calendar_sync === "reconciling" ? (
              <li className="booking__sync">Calendar still syncing — your booking stands</li>
            ) : null}
          </ul>
          {booking.state === "booked" ? (
            <div className="booking__actions">
              <button type="button" className="btn btn--ghost" disabled={!onReschedule || busy} onClick={() => onReschedule?.(booking.code)}>
                Reschedule
              </button>
              <button type="button" className="btn btn--ghost btn--danger" disabled={!onCancel || busy} onClick={() => onCancel?.(booking.code)}>
                Cancel
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <p className="booking__owner">Owner contact 999999999 · demo placeholder, not a real number</p>
    </section>
  );
}
