import type {
  BookingRequest,
  BookingResponse,
  BookingState,
  PdfStatusResponse,
  SlotsResponse,
} from "@/lib/viewmodels/contract";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * The API's `detail`, shown verbatim — unknown and cancelled codes deliberately get
 * the same sentence, and this layer must not reword either. FastAPI's own
 * validation errors send a list instead of a string; their messages are joined.
 */
function detailText(d: unknown): string | null {
  const detail = (d as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((x) => (x as { msg?: unknown } | null)?.msg)
      .filter((m): m is string => typeof m === "string");
    if (msgs.length > 0) return msgs.join("; ");
  }
  return null;
}

/** The plain-HTTP door: bookings by code (arch §11.1). The code is the only credential. */
export class HttpClient {
  constructor(private base: string) {}

  /** True if GET /health answers `{status:"ok"}` within the timeout; never throws. */
  async health(timeoutMs = 8000): Promise<boolean> {
    try {
      const r = await fetch(`${this.base}/health`, { signal: AbortSignal.timeout(timeoutMs) });
      if (!r.ok) return false;
      const d = (await r.json()) as { status?: unknown };
      return d.status === "ok";
    } catch {
      return false;
    }
  }

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    let r: Response;
    try {
      r = await fetch(`${this.base}${path}`, init);
    } catch {
      throw new ApiError(0, "Can't reach the service right now.");
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new ApiError(r.status, detailText(d) ?? r.statusText);
    }
    return r.json();
  }

  private post<T>(path: string, body: unknown): Promise<T> {
    return this.call<T>(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  slots(listing_id: string) {
    return this.post<SlotsResponse>("/bookings/slots", { listing_id });
  }

  book(req: BookingRequest) {
    return this.post<BookingResponse>("/bookings", req);
  }

  cancel(code: string) {
    return this.post<{ code: string; state: BookingState; spoken: string }>(`/bookings/${code}/cancel`, {});
  }

  reschedule(code: string, slot_start_ist: string) {
    return this.post<BookingResponse>(`/bookings/${code}/reschedule`, { code, slot_start_ist });
  }

  /** What happened to the confirmation email, which goes after the booking answers (spec §6.7). */
  pdfStatus(code: string) {
    return this.call<PdfStatusResponse>(`/bookings/${code}/pdf/status`);
  }

  /** Email the PDF again. Limited to three a booking an hour, and the answer says so (spec §6.52). */
  emailPdf(code: string) {
    return this.post<PdfStatusResponse>(`/bookings/${code}/pdf/email`, {});
  }

  /** The PDF, made on demand, as a plain link: the service sends it as an attachment (spec §6.51). */
  pdfUrl(code: string) {
    return `${this.base}/bookings/${code}/pdf`;
  }
}
