import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpClient } from "./http";

const respond = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));

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
