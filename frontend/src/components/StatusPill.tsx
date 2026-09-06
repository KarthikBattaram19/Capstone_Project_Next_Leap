import type { Connection } from "@/lib/state/session";

const TEXT: Record<Connection, string> = {
  connecting: "Connecting…",
  open: "Connected",
  closed: "Disconnected",
  mismatch: "Out of date",
  unreachable: "Can't reach the service",
};

export function StatusPill({ connection, started }: { connection: Connection; started: boolean }) {
  const c = started ? connection : "closed";
  const tone = c === "open" ? "ok" : c === "connecting" ? "wait" : c === "closed" && !started ? "off" : "bad";
  return (
    <div className={"status status--" + tone} aria-live="polite">
      <span className="status__dot" />
      <span className="status__text">{started ? TEXT[c] : "Not connected"}</span>
    </div>
  );
}
