"use client";

import { useState } from "react";

import type { BookingVM, SlotVM } from "@/lib/viewmodels/contract";

import { CalendarIcon, CheckIcon } from "./Icons";

const PDF_TEXT: Record<string, string> = {
  pending: "PDF on its way to your email",
  sent: "PDF sent to your email",
  failed: "The PDF could not be emailed — your code still works",
  render_failed: "The PDF could not be made just now — your code still works",
  // An answer to one "Email it again", shown as the message from the service, never as the
  // email's status: a PDF that already arrived must not start reading as refused (spec §6.52).
  rate_limited: "",
  not_applicable: "",
};

/** When the email did not arrive, or there is no record of one, offer to send it again (spec §6.7). */
const OFFER_EMAIL_AGAIN = new Set(["failed", "render_failed", "not_applicable"]);

/** The email, echoed letter by letter — the highest-error input in the system (arch §10.3). */
function Echo({ value }: { value: string }) {
  if (!value) return null;
  return (
    <p className="booking__echo" aria-label="Email read back letter by letter">
      {Array.from(value).join(" · ")}
    </p>
  );
}

/**
 * The booking on screen: slot, time (IST), the code large, PDF status, the
 * calendar-sync note, Cancel / Reschedule. Every word the service sends back
 * (`spoken` on success, `detail` on an error) is shown here verbatim.
 *
 * `mode` is "book" while slots are offered for a fresh booking (email needed) and
 * "reschedule" while slots are offered to move an existing one (no email: the
 * code is the credential).
 */
export function BookingPanel({
  booking,
  offeredSlots,
  mode = "book",
  listingLabel,
  busy,
  error,
  message,
  onConfirm,
  onRescheduleTo,
  onCancel,
  onReschedule,
  pdfHref,
  onEmailPdf,
}: {
  booking: BookingVM | null;
  offeredSlots: SlotVM[];
  mode?: "book" | "reschedule";
  listingLabel?: string;
  busy?: boolean;
  error?: string | null;
  /** The last `spoken` from the booking API (book, cancel, reschedule, slots). */
  message?: string | null;
  onConfirm?: (slot: SlotVM, email: string) => void;
  /** Reschedule the booking on screen to a slot picked from `offeredSlots`. */
  onRescheduleTo?: (code: string, slot: SlotVM) => void;
  onCancel?: (code: string) => void;
  /** Ask for slots to move the booking on screen to. */
  onReschedule?: (code: string) => void;
  /** Where the PDF for this booking downloads from; the service makes it on demand (spec §6.7). */
  pdfHref?: string;
  /** "Email it again" → POST /bookings/{code}/pdf/email (spec §6.7, §6.52). */
  onEmailPdf?: (code: string) => void;
}) {
  const [slot, setSlot] = useState<SlotVM | null>(offeredSlots[0] ?? null);
  const [email, setEmail] = useState("");

  const confirmed = booking && booking.state === "booked";
  const rescheduling = mode === "reschedule" && !!booking;
  const offering = offeredSlots.length > 0 && (!confirmed || rescheduling);

  return (
    <section className="booking" aria-label="Book a visit">
      <header className="booking__head">
        <div>
          <span className="booking__eyebrow">Site visit</span>
          <h2 className="booking__title">{rescheduling ? "Move the visit" : confirmed ? "Visit booked" : "Book a visit"}</h2>
          {listingLabel ? <p className="booking__listing">{listingLabel}</p> : null}
        </div>
        <CalendarIcon className="booking__glyph" />
      </header>

      {offering ? (
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

          {rescheduling ? (
            <button
              type="button"
              className="btn btn--accent btn--wide"
              disabled={!slot || busy || !onRescheduleTo}
              onClick={() => slot && booking && onRescheduleTo?.(booking.code, slot)}
            >
              {busy ? "Moving…" : "Move the visit to this slot"}
            </button>
          ) : (
            <>
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

              <button
                type="button"
                className="btn btn--accent btn--wide"
                disabled={!slot || !email || busy || !onConfirm}
                onClick={() => slot && onConfirm?.(slot, email)}
              >
                {busy ? "Confirming…" : "Confirm this visit"}
              </button>
            </>
          )}
        </>
      ) : null}

      {!confirmed && !offering && !booking ? (
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
          <p className="booking__ist" aria-label="Slot in Indian Standard Time">
            {booking.slot.start_ist} → {booking.slot.end_ist} · IST
          </p>
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
          {booking.state === "booked" && !rescheduling ? (
            <div className="booking__actions">
              {pdfHref ? (
                <a className="btn btn--ghost" href={pdfHref} download={`visit-${booking.code}.pdf`}>
                  Download PDF
                </a>
              ) : null}
              {OFFER_EMAIL_AGAIN.has(booking.pdf_status) ? (
                <button type="button" className="btn btn--ghost" disabled={!onEmailPdf || busy} onClick={() => onEmailPdf?.(booking.code)}>
                  Email it again
                </button>
              ) : null}
              <button type="button" className="btn btn--ghost" disabled={!onReschedule || busy} onClick={() => onReschedule?.(booking.code)}>
                {busy ? "Working…" : "Reschedule"}
              </button>
              <button type="button" className="btn btn--ghost btn--danger" disabled={!onCancel || busy} onClick={() => onCancel?.(booking.code)}>
                Cancel
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {message ? (
        <p className="booking__message" role="status">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="booking__error" role="alert">
          {error}
        </p>
      ) : null}

      <p className="booking__owner">Owner contact 999999999 · demo placeholder, not a real number</p>
    </section>
  );
}
