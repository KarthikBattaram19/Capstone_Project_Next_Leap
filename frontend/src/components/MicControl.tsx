import { MicIcon } from "./Icons";

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
}: {
  phase: MicPhase;
  onStart: () => void;
  micError: "denied" | "no_device" | null;
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

      {micError ? (
        <div className="mic-error" role="alert">
          {micError === "denied" ? (
            <>
              <p className="mic-error__title">Microphone access was refused.</p>
              <ul className="mic-error__how">
                <li><b>Chrome</b> · click the lock icon in the address bar → Microphone → Allow, then reload.</li>
                <li><b>Firefox</b> · click the microphone icon left of the address bar → remove the block, then reload.</li>
                <li><b>Safari</b> · Safari menu → Settings for This Website → Microphone → Allow.</li>
              </ul>
            </>
          ) : (
            <p className="mic-error__title">No microphone was found. Plug one in, or type below instead.</p>
          )}
        </div>
      ) : null}

      <div className="hero__examples" aria-label="Examples of what you can say">
        <span className="chip chip--example">2 BHK in Koramangala under ₹35,000</span>
        <span className="chip chip--example">near a metro, semi-furnished</span>
        <span className="chip chip--example">why this one?</span>
      </div>
    </div>
  );
}
