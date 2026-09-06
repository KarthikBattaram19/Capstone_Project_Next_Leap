/** What the renter said (interim, then final) and what Nakshatra replied. */
export function TranscriptLine({
  transcript,
  final,
  reply,
}: {
  transcript: string;
  final: boolean;
  reply: string;
}) {
  return (
    <div className="dialogue" aria-live="polite">
      <p className={"dialogue__you" + (final ? " dialogue__you--final" : "")}>
        {transcript ? `“${transcript}${final ? "" : "…"}”` : <span className="dialogue__hint">Say what you are looking for.</span>}
      </p>
      {reply ? <p className="dialogue__reply">{reply}</p> : null}
    </div>
  );
}
