/** A clarifying question from Nakshatra (NeedsInput). Options are chips the renter can tap or say. */
export function QuestionPrompt({
  question,
  onAnswer,
}: {
  question: { question: string; field: string; options: string[] };
  onAnswer?: (text: string) => void;
}) {
  return (
    <section className="question" role="status" aria-live="polite">
      <span className="question__eyebrow">Nakshatra asks</span>
      <p className="question__text">{question.question}</p>
      {question.options.length > 0 ? (
        <div className="question__options">
          {question.options.map((o) => (
            <button
              key={o}
              type="button"
              className="chip chip--option"
              onClick={() => onAnswer?.(o)}
              disabled={!onAnswer}
            >
              {o}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
