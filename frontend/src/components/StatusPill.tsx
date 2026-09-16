import type { Connection } from "@/lib/state/session";

const TEXT: Record<Connection, string> = {
  connecting: "Connecting…",
  open: "Connected",
  closed: "Disconnected",
  mismatch: "Out of date",
  unreachable: "Can't reach the service",
};

/** What the page's health check on load found, before any session exists. */
export type Service = "checking" | "up" | "down";

// Before the renter taps there is no socket, so "Not connected" was true but read as a
// broken site (production, 2026-09-16). Before a session, the pill reports the backend's
// health instead.
const IDLE: Record<Service, { text: string; tone: "ok" | "wait" | "bad" }> = {
  checking: { text: "Checking service…", tone: "wait" },
  up: { text: "Service ready", tone: "ok" },
  down: { text: "Can't reach the service", tone: "bad" },
};

export function StatusPill({
  connection,
  started,
  service,
}: {
  connection: Connection;
  started: boolean;
  service: Service;
}) {
  if (!started) {
    const idle = IDLE[service];
    return (
      <div className={"status status--" + idle.tone} aria-live="polite">
        <span className="status__dot" />
        <span className="status__text">{idle.text}</span>
      </div>
    );
  }
  const tone = connection === "open" ? "ok" : connection === "connecting" ? "wait" : "bad";
  return (
    <div className={"status status--" + tone} aria-live="polite">
      <span className="status__dot" />
      <span className="status__text">{TEXT[connection]}</span>
    </div>
  );
}
