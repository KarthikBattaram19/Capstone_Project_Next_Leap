/**
 * Recovery text for a refused or missing microphone, per browser (spec §6.13).
 * Shown on the welcome screen and again in the workspace beside the typed
 * fallback, so the renter is never left with an input and no way back to voice.
 */
export function MicErrorHelp({ error }: { error: "denied" | "no_device" | null }) {
  if (!error) return null;
  return (
    <div className="mic-error" role="alert">
      {error === "denied" ? (
        <>
          <p className="mic-error__title">Microphone access was refused.</p>
          <ul className="mic-error__how">
            <li>
              <b>Chrome</b> · click the lock icon in the address bar → Microphone → Allow, then reload.
            </li>
            <li>
              <b>Firefox</b> · click the microphone icon left of the address bar → remove the block, then reload.
            </li>
          </ul>
        </>
      ) : (
        <p className="mic-error__title">No microphone was found. Plug one in, or type below instead.</p>
      )}
    </div>
  );
}
