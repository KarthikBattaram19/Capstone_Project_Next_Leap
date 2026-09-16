import type { BookingRequest, BookingResponse, BookingState, SlotsResponse } from "@/lib/viewmodels/contract";

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

  private async post<T>(path: string, body: unknown): Promise<T> {
    let r: Response;
    try {
      r = await fetch(`${this.base}${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "Can't reach the service right now.");
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new ApiError(r.status, detailText(d) ?? r.statusText);
    }
    return r.json();
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
}
