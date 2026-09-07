/**
 * The contract the backend sends the browser.
 *
 * Every interface here is GENERATED: `npm run contract` runs json2ts over
 * `contract/v1.schema.json` (which `python -m scout.contract.export` writes from the
 * pydantic models in `backend/scout/contract/`) and writes `contract.generated.ts`.
 * Never edit `contract.generated.ts` by hand — regenerate it. Any drift between the
 * backend and the browser is a backend-contract defect, fixed there and regenerated,
 * never patched here.
 *
 * This module adds only the two constants (json2ts emits none) and stable names for
 * the unions json2ts hoists to auto-derived, collision-numbered aliases (`Outcome`,
 * `State1`, `PdfStatus`, `CalendarSync`, `Capability` in the generated file). Each
 * alias below is pinned to the contract field it comes from, so consumers never
 * depend on a generated name; the three same-named ones deliberately shadow the
 * star re-export.
 *
 * Nothing in this file is derived by the browser (arch AD-5): every text field
 * arrives already formatted, and "not stated" is already substituted server-side.
 */
import type { BookingVM, Failed, OutcomeMsg } from "./contract.generated";

export * from "./contract.generated";

export const CONTRACT_VERSION = "1";

export const NOT_STATED = "not stated";

/** The five turn-result shapes, discriminated on `kind`. */
export type TurnOutcome = OutcomeMsg["outcome"];

export type BookingState = BookingVM["state"];
export type PdfStatus = BookingVM["pdf_status"];
export type CalendarSync = BookingVM["calendar_sync"];

export type Capability = Failed["capability"];
