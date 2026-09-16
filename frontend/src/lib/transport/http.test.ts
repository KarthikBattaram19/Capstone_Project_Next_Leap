import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpClient } from "./http";

const respond = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

describe("the confirmation PDF by code", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks what happened to the email with a GET", async () => {
    const fetchMock = respond(200, { code: "K7M4PX", pdf_status: "failed", spoken: "It failed." });
    vi.stubGlobal("fetch", fetchMock);
    const r = await new HttpClient("https://api.example").pdfStatus("K7M4PX");
    expect(r.pdf_status).toBe("failed");
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example/bookings/K7M4PX/pdf/status");
    expect((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.method ?? "GET").toBe("GET");
  });

  it("sends the email again with a POST and returns the service's own sentence", async () => {
    const spoken = "That PDF has already been emailed three times in the last hour.";
    const fetchMock = respond(200, { code: "K7M4PX", pdf_status: "rate_limited", spoken });
    vi.stubGlobal("fetch", fetchMock);
    const r = await new HttpClient("https://api.example").emailPdf("K7M4PX");
    expect(r.spoken).toBe(spoken);
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example/bookings/K7M4PX/pdf/email");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("passes the service's 404 sentence through unchanged", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "No matching visit was found for that code." }));
    await expect(new HttpClient("https://api.example").pdfStatus("ZZZZZZ")).rejects.toMatchObject({
      status: 404,
      message: "No matching visit was found for that code.",
    });
  });

  it("builds the download link without a request", () => {
    vi.stubGlobal("fetch", vi.fn());
    expect(new HttpClient("https://api.example").pdfUrl("K7M4PX")).toBe("https://api.example/bookings/K7M4PX/pdf");
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("health check behind the status pill", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is up only when /health answers status ok", async () => {
    const fetchMock = respond(200, { status: "ok", contract_version: "1" });
    vi.stubGlobal("fetch", fetchMock);
    expect(await new HttpClient("https://api.example").health()).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example/health");
  });

  it("is down on a non-2xx answer", async () => {
    vi.stubGlobal("fetch", respond(502, { detail: "bad gateway" }));
    expect(await new HttpClient("https://api.example").health()).toBe(false);
  });

  it("is down on a 200 that is not the health payload", async () => {
    vi.stubGlobal("fetch", respond(200, { hello: "world" }));
    expect(await new HttpClient("https://api.example").health()).toBe(false);
  });

  it("is down, never throws, when the network fails or times out", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(await new HttpClient("https://api.example").health()).toBe(false);
  });
});
