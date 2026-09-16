import type { SessionState } from "@/lib/state/session";
import type { CardVM, SlotVM } from "@/lib/viewmodels/contract";

import { BookingPanel } from "./BookingPanel";
import { CodeEntry } from "./CodeEntry";
import { EmptyState } from "./EmptyState";
import { FailureBanner } from "./FailureBanner";
import { EndCallIcon } from "./Icons";
import { MicErrorHelp } from "./MicErrorHelp";
import { DegradedNotice, MismatchPanel, NoticeList, ReloadNotice, UnreachablePanel, VoiceOutNotice } from "./Notices";
import { QuestionPrompt } from "./QuestionPrompt";
import { ReadbackChips } from "./ReadbackChips";
import { ShortlistCards } from "./ShortlistCards";
import { SnapshotPanel } from "./SnapshotPanel";
import { SourcesPanel } from "./SourcesPanel";
import { TextFallback } from "./TextFallback";
import { TranscriptLine } from "./TranscriptLine";
import { VoiceOrb, orbCaption } from "./VoiceOrb";

export interface WorkspaceHandlers {
  onEnd: () => void;
  onRetry: () => void;
  onReconnect: () => void;
  onSendText: (text: string) => void;
  onEnableVoice: () => void;
  onWhy: (card: CardVM) => void;
  onBook: (listingId: string) => void;
  onConfirm: (slot: SlotVM, email: string) => void;
  /** BookingPanel Cancel → POST /bookings/{code}/cancel. */
  onCancel: (code: string) => void;
  /** BookingPanel Reschedule → POST /bookings/slots for the booking's listing. */
  onReschedule: (code: string) => void;
  /** A slot picked while rescheduling → POST /bookings/{code}/reschedule. */
  onRescheduleTo: (code: string, slot: SlotVM) => void;
  /** CodeEntry Cancel by code → POST /bookings/{code}/cancel; the answer shows under the code field. */
  onCodeCancel: (code: string) => void;
  /** CodeEntry Reschedule with a typed time → POST /bookings/{code}/reschedule. */
  onCodeReschedule: (code: string, when: string) => void;
  /** BookingPanel "Email it again" → POST /bookings/{code}/pdf/email. */
  onEmailPdf: (code: string) => void;
}

export interface WorkspaceExtras {
  bookingBusy?: boolean;
  /** The API's `detail` from the last failed booking call, verbatim. */
  bookingError?: string | null;
  /** The API's `spoken` from the last successful booking call, verbatim. */
  bookingMessage?: string | null;
  /** The last message for a code typed into CodeEntry (`spoken` or `detail`). */
  codeMessage?: string | null;
  bookingListingId?: string | null;
  /** Set while slots are offered to move this booking rather than make a new one. */
  rescheduleCode?: string | null;
  /** True when the tab was reloaded mid-conversation (spec §6.21). */
  reloaded?: boolean;
  /** The download link for a booking's PDF, by code (GET /bookings/{code}/pdf). */
  pdfUrl?: (code: string) => string;
}

function findCard(s: SessionState, id: string | null | undefined): CardVM | undefined {
  if (!id || !s.shortlist) return undefined;
  for (const g of s.shortlist.groups) for (const c of g.cards) if (c.listing_id === id) return c;
  return undefined;
}

/**
 * Everything on screen once a conversation has started. Pure: it draws the
 * session state and calls handlers; it works nothing out (AD-5).
 */
export function Workspace({
  s,
  h,
  x = {},
}: {
  s: SessionState;
  h: WorkspaceHandlers;
  x?: WorkspaceExtras;
}) {
  const explainedId = s.explanation?.listing_id ?? null;
  const bookingCard = findCard(s, x.bookingListingId ?? s.booking?.listing_id);
  const bookingLabel = bookingCard ? `${bookingCard.society_name} · ${bookingCard.locality}` : undefined;
  const showBooking = s.booking !== null || s.offeredSlots.length > 0 || !!x.bookingListingId;
  const hasResults =
    s.readback.length > 0 ||
    s.shortlist !== null ||
    s.explanation !== null ||
    s.emptyResult !== null ||
    s.question !== null ||
    s.lastFailure !== null ||
    showBooking;

  return (
    <main className="work">
      <section className="voice" aria-label="Voice">
        <VoiceOrb state={s.listening} />
        <p className={"voice__caption voice__caption--" + s.listening}>
          <span className="voice__caption-dot" />
          {orbCaption(s.listening)}
        </p>
        <TranscriptLine transcript={s.transcript} final={s.transcriptFinal} reply={s.reply} />
        <button type="button" className="btn btn--ghost btn--pill voice__end" onClick={h.onEnd}>
          <EndCallIcon className="btn__icon" />
          End conversation
        </button>
        <div className="voice__extras">
          {s.voiceOut !== "on" ? <VoiceOutNotice state={s.voiceOut} onEnable={h.onEnableVoice} /> : null}
          <MicErrorHelp error={s.micError} />
          {s.micError ? <TextFallback onSend={h.onSendText} disabled={s.connection !== "open"} /> : null}
          {x.reloaded ? <ReloadNotice /> : null}
        </div>
      </section>

      <section className="results" aria-label="Results">
        {s.connection === "unreachable" ? <UnreachablePanel onRetry={h.onReconnect} /> : null}
        {s.connection === "mismatch" ? <MismatchPanel /> : null}

        {s.readback.length > 0 ? <ReadbackChips items={s.readback} /> : null}
        {s.question ? <QuestionPrompt question={s.question} onAnswer={h.onSendText} /> : null}
        {s.lastFailure ? <FailureBanner failure={s.lastFailure} onRetry={h.onRetry} /> : null}
        {s.degraded ? <DegradedNotice degraded={s.degraded} /> : null}
        <NoticeList notices={s.notices} />
        {s.emptyResult ? <EmptyState result={s.emptyResult} /> : null}

        {s.shortlist ? (
          <ShortlistCards shortlist={s.shortlist} selectedId={explainedId} onWhy={h.onWhy} onShowUnknown={(f) => h.onSendText(`Show me the ones where the ${f} is not stated`)} />
        ) : null}

        {s.explanation ? (
          <>
            <SnapshotPanel explanation={s.explanation} snapshot={s.snapshot} onBook={h.onBook} />
            <SourcesPanel sources={s.explanation.sources} />
          </>
        ) : null}

        {showBooking ? (
          <BookingPanel
            key={(x.rescheduleCode ? "move:" : "") + (x.bookingListingId ?? s.booking?.code ?? "booking")}
            booking={s.booking}
            offeredSlots={s.offeredSlots}
            mode={x.rescheduleCode && x.rescheduleCode === s.booking?.code ? "reschedule" : "book"}
            listingLabel={bookingLabel}
            busy={x.bookingBusy}
            error={x.bookingError}
            message={x.bookingMessage}
            onConfirm={h.onConfirm}
            onRescheduleTo={h.onRescheduleTo}
            onCancel={h.onCancel}
            onReschedule={h.onReschedule}
            pdfHref={s.booking && x.pdfUrl ? x.pdfUrl(s.booking.code) : undefined}
            onEmailPdf={h.onEmailPdf}
          />
        ) : null}

        {!hasResults && s.connection === "open" ? (
          <div className="results__placeholder">
            <b>Nothing to show yet.</b>
            <span>
              Tell Nakshatra what you need — a locality, how many bedrooms, a monthly budget — and the shortlist
              appears here. Ask <i>“why this one?”</i> about any listing to see the reasons and their sources.
            </span>
          </div>
        ) : null}

        <CodeEntry onCancel={h.onCodeCancel} onReschedule={h.onCodeReschedule} busy={x.bookingBusy} message={x.codeMessage} />
      </section>
    </main>
  );
}
