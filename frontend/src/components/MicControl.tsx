import { MicIcon } from "./Icons";
import { MicErrorHelp } from "./MicErrorHelp";
import { ReloadNotice } from "./Notices";

export type MicPhase = "idle" | "connecting";

/**
 * The hero microphone (welcome screen). One click unlocks audio and starts the
 * session — both must happen inside the same gesture (spec §6.15). The button is
 * disabled from the click until the mic is live, so a second click cannot open
 * a second session (the double-session noise seen on production 2026-09-06).
 */
export function MicControl({
  phase,
  onStart,
  micError,
  reloaded,
}: {
  phase: MicPhase;
  onStart: () => void;
  micError: "denied" | "no_device" | null;
  /** The tab was reloaded mid-conversation: the conversation is gone (spec §6.21). */
  reloaded?: boolean;
}) {
  const connecting = phase === "connecting";
  return (
    <div className="hero">
      <p className="hero__eyebrow">
        <span className="hero__brand">Nakshatra</span>
        <span className="hero__dot" />
        <span>your Bengaluru property scout</span>
      </p>

      <button
        type="button"
        className={"mic" + (connecting ? " mic--connecting" : "")}
        onClick={onStart}
        disabled={connecting}
        aria-label={connecting ? "Connecting" : "Tap to talk to Nakshatra"}
      >
        <span className="mic__glow" />
        <span className="mic__disc">
          <MicIcon className="mic__icon" />
        </span>
      </button>

      <p className="hero__label">{connecting ? "Connecting…" : "Tap to talk to Nakshatra"}</p>
      <p className="hero__sub">
        {connecting ? "Unlocking audio and opening the microphone" : "She greets you first, then you say what you need"}
      </p>

      <MicErrorHelp error={micError} />

      {reloaded ? <ReloadNotice /> : null}

      <div className="hero__examples" aria-label="Examples of what you can say">
        <span className="chip chip--example">2 BHK in Koramangala under ₹35,000</span>
        <span className="chip chip--example">near a metro, semi-furnished</span>
        <span className="chip chip--example">why this one?</span>
      </div>
    </div>
  );
}
