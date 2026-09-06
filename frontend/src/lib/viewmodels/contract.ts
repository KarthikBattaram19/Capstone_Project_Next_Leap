/**
 * The contract the backend sends the browser — transcribed BY HAND from
 * Docs/Implementation_Plan_Addendum.md, Task 1.5, on 2026-09-06.
 *
 * Task 1.5 has not been built yet, so `contract/v1.schema.json` does not exist and
 * `npm run contract` (json2ts) cannot generate this file. When Task 1.5 lands, run
 * it: the generated output REPLACES this file, and any drift between the two is a
 * Task 1.5 defect to fix there, never here.
 *
 * Nothing in this file is derived by the browser (arch AD-5): every text field
 * arrives already formatted, and "not stated" is already substituted server-side.
 */

export const CONTRACT_VERSION = "1";

export const NOT_STATED = "not stated";

export type Capability =
  | "speech_in"
  | "understanding"
  | "explanation"
  | "speech_out"
  | "calendar"
  | "mail";

// ---------------------------------------------------------------- view-models

export interface CommuteRowVM {
  /** "Metro" | "Bus stop" | "Work" */
  what: string;
  /** "1.1 km" | "not stated" */
  value_text: string;
  /** "by route" | "straight-line" | "" (only when value_text is "not stated") */
  badge: string;
  /** "[OSM routing — precomputed 2026-09-01]" … */
  full_label: string;
  spoken: string;
}

export interface CardVM {
  listing_id: string;
  rank: number;
  /** the card's primary label (spec §4) */
  locality: string;
  society_name: string;
  rent: string;
  deposit: string;
  maintenance: string;
  bhk_type: string;
  /** "1100 sq ft (carpet)" | "not stated" — labelled sq ft, never "area" */
  square_footage: string;
  floor: string;
  parking: string;
  furnishing: string;
  amenities: string[];
  available_from: string;
  transit: CommuteRowVM;
  /** absent, not empty, when no commute point was stated */
  your_commute?: CommuteRowVM | null;
}

export interface UnknownGroupVM {
  field: string;
  listing_ids: string[];
  /** "3 more where the deposit is not stated — want to see them?" */
  spoken: string;
}

export interface LocalityGroupVM {
  locality: string;
  count: number;
  cards: CardVM[];
}

export interface ShortlistVM {
  /** the ranked order; grouping never reorders it */
  order: string[];
  groups: LocalityGroupVM[];
  unknown_on: UnknownGroupVM[];
}

export interface CitationVM {
  /** "dataset:kor-001" | "osm:kor-001:nearest_metro" | "guide:kor-0-3" */
  ref: string;
  /** "[Wikipedia — Koramangala]" | "[OSM routing — precomputed 2026-09-01]" */
  label: string;
  title?: string | null;
  url?: string | null;
  method?: string | null;
  timing?: string | null;
  as_of?: string | null;
}

export interface ClaimVM {
  text: string;
  citation_refs: string[];
}

export interface SnapshotVM {
  listing_id: string;
  claims: ClaimVM[];
  gaps: string[];
  /** "Limited neighborhood data available" */
  limited: boolean;
}

export interface ExplanationVM {
  listing_id: string;
  opener: string;
  claims: ClaimVM[];
  gaps: string[];
  sources: CitationVM[];
}

export interface SlotVM {
  /** ISO 8601 with +05:30 */
  start_ist: string;
  end_ist: string;
  /** "Tuesday the 2nd at 4 pm" */
  spoken: string;
}

export type BookingState = "offered" | "confirming" | "booked" | "cancelled" | "withdrawn";
export type PdfStatus = "pending" | "sent" | "failed" | "not_applicable";
export type CalendarSync = "complete" | "reconciling";

export interface BookingVM {
  code: string;
  listing_id: string;
  slot: SlotVM;
  state: BookingState;
  pdf_status: PdfStatus;
  calendar_sync: CalendarSync;
}

export interface AnsweredViewModel {
  constraints_readback: string[];
  shortlist?: ShortlistVM | null;
  explanation?: ExplanationVM | null;
  snapshot?: SnapshotVM | null;
  booking?: BookingVM | null;
  offered_slots?: SlotVM[];
  /** e.g. "One listing … has been removed." */
  notices?: string[];
}

// ------------------------------------------------------------------ outcomes

export interface UnmetConstraint {
  field: string;
  value: string;
  binding: boolean;
}

interface OutcomeBase {
  /** every outcome is both spoken and shown (spec §6.0 principle 3) */
  spoken: string;
}

export interface Answered extends OutcomeBase {
  kind: "answered";
  view_model: AnsweredViewModel;
}

/** Empty is a RESULT. */
export interface Empty extends OutcomeBase {
  kind: "empty";
  unmet: UnmetConstraint[];
  suggestions: string[];
}

export interface Degraded extends OutcomeBase {
  kind: "degraded";
  view_model: AnsweredViewModel;
  missing: string[];
  why: string;
}

/** Failed is an ERROR. It cannot share a renderer with Empty (A5). */
export interface Failed extends OutcomeBase {
  kind: "failed";
  capability: Capability;
  tell_renter: string;
  retry_worth_it: boolean;
}

export interface NeedsInput extends OutcomeBase {
  kind: "needs_input";
  question: string;
  field: string;
  options: string[];
}

export type TurnOutcome = Answered | Empty | Degraded | Failed | NeedsInput;

// ---------------------------------------------------------------------- HTTP

export interface BookingRequest {
  session_id: string;
  listing_id: string;
  slot_start_ist: string;
  email: string;
}

export interface BookingResponse {
  booking: BookingVM;
  spoken: string;
}

export interface CancelRequest {
  code: string;
}

export interface RescheduleRequest {
  code: string;
  slot_start_ist: string;
}

export interface SlotsResponse {
  slots: SlotVM[];
}

export interface AvailabilityToggle {
  listing_id: string;
  available: boolean;
}
