import type { BookingRequest, BookingResponse, SlotsResponse } from "@/lib/viewmodels/contract";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The plain-HTTP door: bookings by code (arch §11.1). The code is the only credential. */
export class HttpClient {
  constructor(private base: string) {}

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
      throw new ApiError(r.status, d.detail ?? r.statusText);
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
    return this.post<{ code: string; state: string; spoken: string }>(`/bookings/${code}/cancel`, {});
  }

  reschedule(code: string, slot_start_ist: string) {
    return this.post<BookingResponse>(`/bookings/${code}/reschedule`, { code, slot_start_ist });
  }
}
