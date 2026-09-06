"use client";

import { EmptyState } from "@/components/EmptyState";
import { FailureBanner } from "@/components/FailureBanner";
import { MicControl } from "@/components/MicControl";
import { DegradedNotice, MismatchPanel, ReloadNotice, UnreachablePanel, VoiceOutNotice } from "@/components/Notices";
import { QuestionPrompt } from "@/components/QuestionPrompt";
import { StatusPill } from "@/components/StatusPill";
import { VoiceOrb, orbCaption } from "@/components/VoiceOrb";
import { Workspace, type WorkspaceHandlers } from "@/components/Workspace";
import type { Listening } from "@/lib/state/session";

import { states } from "./fixtures";

const noop = () => {};
const h: WorkspaceHandlers = {
  onEnd: noop,
  onRetry: noop,
  onReconnect: noop,
  onSendText: noop,
  onEnableVoice: noop,
  onWhy: noop,
  onBook: noop,
  onConfirm: noop,
  onCancel: noop,
  onReschedule: noop,
  onLookup: noop,
};

function Section({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <section id={id} className="preview__section">
      <h2 className="preview__label">{label}</h2>
      {children}
    </section>
  );
}

/**
 * Every screen and state with sample data, so the design can be reviewed
 * without a backend. The data is invented for this page and is not from the
 * dataset. Handlers do nothing.
 */
export default function PreviewPage() {
  return (
    <div className="preview">
      <p className="preview__label">Nakshatra — design preview · sample data, not the dataset</p>

      <Section id="welcome" label="1 · Welcome">
        <div className="preview__frame">
          <div className="app__top" style={{ position: "absolute" }}>
            <StatusPill connection="closed" started={false} />
          </div>
          <div className="welcome">
            <MicControl phase="idle" onStart={noop} micError={null} />
          </div>
        </div>
      </Section>

      <Section id="orb" label="Orb states">
        <div className="preview__orbs">
          {(["listening", "processing", "speaking"] as Listening[]).map((st) => (
            <div key={st} className="preview__orb">
              <VoiceOrb state={st} size={180} />
              <p className={"voice__caption voice__caption--" + st}>
                <span className="voice__caption-dot" />
                {orbCaption(st)}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section id="listening" label="2a · Conversation just started">
        <div className="preview__frame">
          <Workspace s={states.listening} h={h} />
        </div>
      </Section>

      <Section id="results" label="2b · Live conversation with results">
        <div className="preview__frame">
          <Workspace s={states.results} h={h} />
        </div>
      </Section>

      <Section id="explanation" label="3 · Why this one">
        <div className="preview__frame">
          <Workspace s={states.explanation} h={h} />
        </div>
      </Section>

      <Section id="offering" label="4a · Slots offered">
        <div className="preview__frame">
          <Workspace s={states.offering} h={h} x={{ bookingListingId: "kor-001" }} />
        </div>
      </Section>

      <Section id="booking" label="4b · Visit booked">
        <div className="preview__frame">
          <Workspace s={states.booking} h={h} />
        </div>
      </Section>

      <Section id="states" label="5 · States">
        <div className="preview__grid">
          <QuestionPrompt question={states.question.question!} onAnswer={noop} />
          <EmptyState result={states.empty.emptyResult!} />
          <FailureBanner failure={states.failed.lastFailure!} onRetry={noop} />
          <DegradedNotice degraded={states.degraded.degraded!} />
          <UnreachablePanel onRetry={noop} />
          <MismatchPanel />
          <VoiceOutNotice state="blocked" onEnable={noop} />
          <VoiceOutNotice state="unavailable" onEnable={noop} />
          <ReloadNotice />
        </div>
        <div className="preview__frame">
          <div className="welcome" style={{ minHeight: 0 }}>
            <MicControl phase="idle" onStart={noop} micError="denied" />
          </div>
        </div>
      </Section>

      <Section id="unreachable" label="5b · Service unreachable, shortlist kept">
        <div className="preview__frame">
          <Workspace s={states.unreachable} h={h} />
        </div>
      </Section>
    </div>
  );
}
