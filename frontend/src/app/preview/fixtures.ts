/**
 * Sample data for /preview — shaped exactly like the Task 1.5 contract so the
 * components are exercised as they will be in production. Every value here is
 * invented for the preview and is labelled so on the page; none of it comes
 * from the dataset.
 */
import type { SessionState } from "@/lib/state/session";
import { initial } from "@/lib/state/session";
import type { BookingVM, CardVM, ExplanationVM, ShortlistVM, SlotVM } from "@/lib/viewmodels/contract";

const OSM = "[OSM routing — precomputed 2026-09-01]";
const OSM_SL = "[OSM straight-line — precomputed 2026-09-01]";
const LIVE_SL = "[Straight-line from coordinates — computed now]";

function card(p: Partial<CardVM> & Pick<CardVM, "listing_id" | "rank" | "locality">): CardVM {
  return {
    society_name: "not stated",
    rent: "not stated",
    deposit: "not stated",
    maintenance: "not stated",
    bhk_type: "not stated",
    square_footage: "not stated",
    floor: "not stated",
    parking: "not stated",
    furnishing: "not stated",
    amenities: [],
    available_from: "not stated",
    transit: { what: "Metro", value_text: "not stated", badge: "", full_label: OSM, spoken: "" },
    your_commute: null,
    ...p,
  };
}

export const cards: CardVM[] = [
  card({
    listing_id: "kor-001",
    rank: 1,
    locality: "Koramangala",
    society_name: "Raheja Residency",
    rent: "₹32,000",
    deposit: "₹1,20,000",
    maintenance: "₹3,500",
    bhk_type: "2 BHK",
    square_footage: "1,150 sq ft (carpet)",
    floor: "3 of 5",
    parking: "1 covered",
    furnishing: "Semi-furnished",
    amenities: ["Power backup", "Lift", "Security 24/7", "Gym"],
    available_from: "1 Oct 2026",
    transit: { what: "Metro", value_text: "1.1 km", badge: "by route", full_label: OSM, spoken: "1.1 km by route" },
    your_commute: { what: "Work", value_text: "5.8 km", badge: "straight-line", full_label: LIVE_SL, spoken: "" },
  }),
  card({
    listing_id: "kor-014",
    rank: 2,
    locality: "Koramangala",
    society_name: "Pinegrove Apartments",
    rent: "₹34,500",
    deposit: "₹1,50,000",
    bhk_type: "2 BHK",
    square_footage: "1,020 sq ft (built-up)",
    floor: "2",
    parking: "1 open",
    furnishing: "Semi-furnished",
    amenities: ["Lift", "Power backup"],
    available_from: "Immediate",
    transit: { what: "Metro", value_text: "1.4 km", badge: "by route", full_label: OSM, spoken: "" },
    your_commute: { what: "Work", value_text: "6.2 km", badge: "straight-line", full_label: LIVE_SL, spoken: "" },
  }),
  card({
    listing_id: "hsr-007",
    rank: 3,
    locality: "HSR Layout",
    society_name: "Independent builder floor",
    rent: "₹30,000",
    maintenance: "₹1,500",
    bhk_type: "2 BHK",
    square_footage: "980 sq ft (carpet)",
    floor: "1",
    parking: "Bike only",
    furnishing: "Unfurnished",
    amenities: ["Power backup"],
    available_from: "15 Oct 2026",
    transit: { what: "Metro", value_text: "2.1 km", badge: "straight-line", full_label: OSM_SL, spoken: "" },
    your_commute: { what: "Work", value_text: "4.9 km", badge: "straight-line", full_label: LIVE_SL, spoken: "" },
  }),
];

export const shortlist: ShortlistVM = {
  order: ["kor-001", "kor-014", "hsr-007"],
  groups: [
    { locality: "Koramangala", count: 2, cards: [cards[0], cards[1]] },
    { locality: "HSR Layout", count: 1, cards: [cards[2]] },
  ],
  unknown_on: [
    {
      field: "deposit",
      listing_ids: ["kor-022", "kor-031", "hsr-012"],
      spoken: "3 more where the deposit is not stated — want to see them?",
    },
  ],
};

export const readback = ["2 BHK", "Koramangala, HSR Layout", "under ₹35,000", "move in Oct 2026"];

export const explanation: ExplanationVM = {
  listing_id: "kor-001",
  opener: "₹32,000 for a 2 BHK, 1.1 km from Koramangala metro by route.",
  claims: [
    { text: "The deposit is ₹1,20,000, under four months' rent.", citation_refs: ["dataset:kor-001"] },
    {
      text: "The nearest bus stop is 350 m away by route, so a bus commute does not depend on the metro.",
      citation_refs: ["osm:kor-001:nearest_bus_stop"],
    },
    {
      text: "Koramangala's inner blocks are described as residential with tree-lined streets, while the 80 Feet Road side is commercial and busy at night.",
      citation_refs: ["guide:kor-0-3"],
    },
  ],
  gaps: ["I don't have a maintenance breakdown for this listing.", "The guide says nothing about water supply."],
  sources: [
    { ref: "dataset:kor-001", label: "[Listing dataset — kor-001, as of 2026-09-05]", as_of: "2026-09-05" },
    {
      ref: "osm:kor-001:nearest_bus_stop",
      label: "[OSM routing — precomputed 2026-09-01]",
      method: "routed",
      timing: "precomputed",
      as_of: "2026-09-01",
    },
    {
      ref: "guide:kor-0-3",
      label: "[Wikipedia — Koramangala]",
      url: "https://en.wikipedia.org/wiki/Koramangala",
      title: "Koramangala",
    },
  ],
};

export const slots: SlotVM[] = [
  { start_ist: "2026-09-08T16:00:00+05:30", end_ist: "2026-09-08T17:00:00+05:30", spoken: "Tue 8 Sep · 4:00–5:00 pm IST" },
  { start_ist: "2026-09-09T11:00:00+05:30", end_ist: "2026-09-09T12:00:00+05:30", spoken: "Wed 9 Sep · 11:00 am–12:00 pm IST" },
  { start_ist: "2026-09-12T10:00:00+05:30", end_ist: "2026-09-12T11:00:00+05:30", spoken: "Sat 12 Sep · 10:00–11:00 am IST" },
];

export const booking: BookingVM = {
  code: "K7M4PX",
  listing_id: "kor-001",
  slot: slots[0],
  state: "booked",
  pdf_status: "sent",
  calendar_sync: "reconciling",
};

const live: SessionState = { ...initial, connection: "open" };

export const states = {
  listening: {
    ...live,
    listening: "listening" as const,
    transcript: "Looking for a 2 BHK in Koramangala under 35",
    transcriptFinal: false,
  },
  results: {
    ...live,
    listening: "speaking" as const,
    transcript: "Looking for a 2 BHK in Koramangala or HSR under 35,000 with metro access",
    transcriptFinal: true,
    reply: "I found three flats under ₹35,000 across Koramangala and HSR Layout. Two are within 1.5 km of a metro station by route. Want to hear why the first one?",
    readback,
    shortlist,
  },
  explanation: {
    ...live,
    listening: "idle" as const,
    transcript: "Why the first one?",
    transcriptFinal: true,
    reply: "₹32,000 for a 2 BHK, 1.1 km from Koramangala metro by route. The deposit is under four months' rent.",
    readback,
    shortlist,
    explanation,
    snapshot: { listing_id: "kor-001", claims: explanation.claims, gaps: explanation.gaps, limited: true },
  },
  booking: {
    ...live,
    listening: "idle" as const,
    transcript: "Book the first one on Tuesday at four",
    transcriptFinal: true,
    reply: "Your visit is booked for Tuesday the 8th at 4 pm. Your code is K, 7, M, 4, P, X. The PDF is on its way.",
    readback,
    shortlist,
    booking,
  },
  offering: {
    ...live,
    listening: "processing" as const,
    transcript: "Book a visit to the first one",
    transcriptFinal: true,
    reply: "Here are the next three free hours on the owner's calendar.",
    readback,
    shortlist,
    offeredSlots: slots,
  },
  thinking: {
    ...live,
    listening: "processing" as const,
    transcript: "Drop anything above 33,000",
    transcriptFinal: true,
    readback,
    shortlist,
  },
  question: {
    ...live,
    readback: ["2 BHK", "Koramangala"],
    question: {
      question: "Which do you mean by “thirty five” — ₹35,000 a month, or ₹3,50,000 as the deposit?",
      field: "rent_max",
      options: ["₹35,000 a month", "₹3,50,000 deposit"],
    },
  },
  empty: {
    ...live,
    readback: ["2 BHK", "Koramangala", "under ₹25,000"],
    reply: "Nothing under ₹25,000 in Koramangala.",
    emptyResult: {
      unmet: [{ field: "rent_max", value: "₹25,000", binding: true }],
      suggestions: ["try ₹30,000", "add HSR Layout"],
      spoken: "Nothing under ₹25,000 in Koramangala.",
    },
  },
  failed: {
    ...live,
    readback,
    shortlist,
    lastFailure: {
      capability: "explanation",
      tell_renter: "Your shortlist is unchanged. I can try the explanation again in a moment.",
      retry_worth_it: true,
    },
  },
  degraded: {
    ...live,
    readback,
    shortlist,
    degraded: { missing: ["explanation"], why: "the explanation service did not answer in time." },
  },
  unreachable: { ...live, connection: "unreachable" as const, readback, shortlist },
  mismatch: { ...live, connection: "mismatch" as const },
  micDenied: { ...live, micError: "denied" as const },
  voiceBlocked: { ...live, voiceOut: "blocked" as const, readback, shortlist },
};
