import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BookingVM, PdfStatus } from "@/lib/viewmodels/contract";

import { BookingPanel } from "./BookingPanel";

const slot = { start_ist: "2026-09-15T10:00:00+05:30", end_ist: "2026-09-15T11:00:00+05:30", spoken: "Mon 10 am" };

const booked = (pdf_status: PdfStatus): BookingVM => ({
  code: "K7M4PX",
  listing_id: "a",
  slot,
  state: "booked",
  pdf_status,
  calendar_sync: "complete",
});

const panel = (pdf_status: PdfStatus, onEmailPdf = vi.fn()) =>
  render(
    <BookingPanel
      booking={booked(pdf_status)}
      offeredSlots={[]}
      pdfHref="https://api.example/bookings/K7M4PX/pdf"
      onEmailPdf={onEmailPdf}
      onCancel={vi.fn()}
      onReschedule={vi.fn()}
    />,
  );

describe("the confirmation PDF on a booked visit (spec §6.7, §6.51, §6.52)", () => {
  afterEach(cleanup);

  it("always offers the PDF as a download, whatever happened to the email", () => {
    for (const status of ["pending", "sent", "failed", "render_failed", "not_applicable"] as const) {
      panel(status);
      const link = screen.getByText("Download PDF").closest("a");
      expect(link?.getAttribute("href")).toBe("https://api.example/bookings/K7M4PX/pdf");
      cleanup();
    }
  });

  it("says a failed email plainly and offers to send it again", () => {
    const onEmailPdf = vi.fn();
    panel("failed", onEmailPdf);
    expect(screen.getByText("The PDF could not be emailed — your code still works")).toBeTruthy();
    fireEvent.click(screen.getByText("Email it again"));
    expect(onEmailPdf).toHaveBeenCalledWith("K7M4PX");
  });

  it("names a PDF that could not be made, and still offers the retry", () => {
    panel("render_failed");
    expect(screen.getByText("The PDF could not be made just now — your code still works")).toBeTruthy();
    expect(screen.getByText("Email it again")).toBeTruthy();
  });

  it("does not offer to resend an email that arrived", () => {
    panel("sent");
    expect(screen.getByText("PDF sent to your email")).toBeTruthy();
    expect(screen.queryByText("Email it again")).toBeNull();
  });

  it("does not offer to resend while the email is still going", () => {
    panel("pending");
    expect(screen.queryByText("Email it again")).toBeNull();
  });

  it("never shows a refused resend as the email's status", () => {
    // "rate_limited" answers one request; the service's sentence arrives as the message.
    const { container } = panel("rate_limited");
    expect(container.querySelector(".booking__pdf")).toBeNull();
  });
});
