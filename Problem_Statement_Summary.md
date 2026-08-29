# Voice-based AI Property Scout Platform – Bengaluru

**Condensed problem statement.** This is a working summary of `Problem_Statement_Detailed.md` (v3.9). It carries every decision that changes what gets built; the full document carries the reasoning behind each one. **Where the two disagree, the full document governs.** Section numbers below match it.

---

## 1. Problem & Scope

Tenants don't struggle to *find* listings. They struggle to judge whether a listing fits their life — is the commute realistic, is the area safe, is the extra room worth the extra rent.

**Solution:** a deployed, voice-first AI property scout that collects spoken preferences, shortlists real listings, explains every choice with citations, and books a site visit on Google Calendar for tenant and owner — with every neighborhood claim grounded in real data.

| Constraint | Decision |
|---|---|
| City | **Bengaluru only** |
| Listings | **Up to 10 per locality**, scraped once from bengaluru.rent |
| Locality set | **Not pinned in advance** — whatever the source has available pins for. The list, per-locality counts and total are an **output of step 1**, documented after the scrape |
| "Up to" | A **ceiling, not a target.** Under-supplied localities keep their real count (never padded); over-supplied ones are curated to the 10 best-populated records by a documented rule |
| RAG corpus | **1–3 documents per *locality*** (not per listing), shared by that locality's ≤10 listings |

---

## 2. Core Capabilities

- **2.1 Preference collection** — extracts budget, bedrooms, must-haves, commute point, preferred areas. Max 5 clarifying questions. **All constraints confirmed verbally before the shortlist** — the primary defence against STT mishearing. English only (MVP); Indian-English accents in scope.
- **2.2 Refinement** — *"drop anything above 40k"*. Only the affected part changes; unrelated listings and their order are preserved. Edits are cumulative. Contradictions trigger a question, not silent breakage.
- **2.3 Explanation** — every neighborhood claim cites its source. Missing data is declared: *"I don't have safety data for this area"* is a correct answer.
- **2.4 Booking** — one demo Google account, two secondary calendars (**Tenant** and **Owner**), single OAuth. Slots from the Owner calendar's free/busy: **next 7 days, 10:00–18:00 IST, 1-hour**, first 3 offered. Both calendar events written atomically. A **6-character alphanumeric code** is the lookup key for cancel/reschedule (no login). Reschedule keeps the same code and re-issues the PDF. Both are refused after the slot start; both may happen more than once.
- **2.5 PDF + email** — generated on confirmation, emailed via Gmail, then discarded (**no storage, no retention**). Owner contact is the labelled demo placeholder `999999999` — deliberately invalid, so nobody dials a real number. Tenant is the only recipient.

### Commute-method disclosure (2.3 — a correctness requirement, not presentation)

Two methods are in use, so every number must name **which**:

| Claim | Voice must say | UI label |
|---|---|---|
| Listing-anchored, routed | "…**by route**" | `[OSM routing — precomputed <date>]` |
| Listing-anchored, straight-line fallback | "…**in a straight line**" | `[OSM straight-line — precomputed <date>]` |
| Tenant's commute point (default) | "…**straight-line** … real road distance will be longer" | `[Straight-line from coordinates — computed now]` |
| Tenant's commute point, routed | "…**by route**" | `[OSM routing — live]` |

The words *straight line* / *by route* are **mandatory in speech**. A bare "about 15 minutes to the metro" is a red-line failure: unreproducible, and a straight-line figure heard as a travel time understates a Bengaluru commute enough to change a decision. Straight-line answers carry the caveat **in the same breath**, not as a footnote.

---

## 3. Data

### 3.1 Listings — the searchable schema
Scraped once → static dataset. Every field is voice-filterable and asserted in Suite A: `locality`, `bhk_type` (1RK/1BHK/2BHK/3BHK/3BHK+, held alongside raw `bedrooms`), `bathrooms`, `rent`, `deposit`, `maintenance_charges`, `property_type`, `furnishing`, `square_footage` (carpet vs built-up recorded explicitly), `floor`/`total_floors`, `lift`, `parking` (two/four-wheeler/both/none), `amenities`, `available_from`, `availability_status`, `society_name`, `coordinates`.

Three rules that govern the whole schema:
- **Fields are confirmed at scrape time, not assumed.** Anything the source doesn't publish goes in the gap report alongside the availability marker.
- **`null` is a real, displayable value** — *"not stated for this listing"*. Never inferred, never a default (a missing deposit is not ₹0).
- **`null` never silently satisfies a must-have.** Unknowns surface as their own *"unknown on this filter"* group the tenant can opt into — otherwise every sparse field becomes an invisible filter and a wider schema makes results quietly worse.

Also: budget filters on `rent` (deposit and maintenance always *shown*); dedup on exact address or coordinates within 50 m; availability is a dataset flag that can flip via admin toggle or a booking-time recheck, and an unavailable listing is removed automatically with the tenant told.

### 3.2 PII
Owner/agent names and numbers stripped **before** data reaches the dataset, UI, logs or transcripts. The labelled placeholder is the only contact value anywhere.

### 3.3 Neighborhood guidance (RAG)
**Pre-built closed index**, no live fetching. Wikipedia and comparable open city guides, chunked with per-chunk attribution. **Retrieval is listing-scoped** — a query about listing X reads only its locality's documents. This is the structural defence against cross-locality contamination, and it gets larger, not smaller, as localities multiply. Gaps show *"Limited neighborhood data available"* — never filled from model knowledge.

### 3.4 Amenities & transit (OSM MCP — **precomputed**)
All amenity/transit/POI claims come from the OpenStreetMap MCP, resolved **once at index time** and stored on the listing record. **No OSM call happens inside a tenant's turn.** Grounding is unchanged: OSM stays the sole source, each value keeps its attribution and retrieval date. The query set is fixed and documented so coverage is uniform; empty results store as `null`.

| Claim | When | Method |
|---|---|---|
| Listing-anchored (nearest metro/bus, distances, POIs) | Index time | OSM MCP, fixed query set |
| Tenant's commute point | Query time — the destination isn't known until they speak | **Straight-line from stored coordinates** (local arithmetic, no network call). MCP routing only if it fits the budget |

### 3.5 Grounding boundary
| Claim type | Sole permitted source |
|---|---|
| Listing facts (every schema field) | Scraped dataset. **No fallback** — absent means `null` |
| Amenities, transit, distances | OSM MCP (precomputed) |
| Neighborhood character, safety | Closed RAG index, with citation |
| Anything else | Not asserted — declared unavailable |

---

## 4. Companion UI (desktop-first, 1024px+)

- **Shortlist cards** — **locality is the primary label** (society name beneath), then rent, **deposit and maintenance** (real cost visible up front), BHK, sq ft, floor, parking, furnishing, amenities. Unstated fields read *"not stated"* — never blank, never zero. Cards are **grouped by locality**; grouping is presentation only and must not reorder the shortlist.
- **Commute rows carry their method badge** (`by route` / `straight-line`); the full label with precomputed-vs-live status and index date appears in the expanded view, snapshot panel and Sources. **The badge is never dropped for space** — if the card is tight, the number comes off, not the label. `straight-line` badges are visually distinct.
- **Neighborhood snapshot panel** per listing, every entry cited.
- **Mic button + live transcript** with clear recording/listening/processing states.
- **Sources section** — a bare `[OSM]` is insufficient; entries resolve to method and moment.
- **Visit-confirmation panel** — slot, code, PDF status, cancel/reschedule.
- **Empty state** names the unmet constraints and suggests relaxations; the system never auto-relaxes.

---

## 5. Architecture

### 5.1 Voice pipeline
- **STT — Deepgram.** Keyterm boosting for **every locality in the scraped set**, generated from the dataset rather than hand-written, plus Indian-English amount normalisation ("35k" → 35000, "1.2 lakh" → 120000). This is the single most likely real-world failure mode.
- **LLM — two models, two providers**, because the jobs have opposite requirements:

| Role | Model | Why |
|---|---|---|
| **Job 1** — extraction & edit routing | Groq `openai/gpt-oss-120b`, `temperature=0` | Latency-critical; needs schema conformance, not reasoning. **Latency-verify at p99 before locking**; drop to a lighter Groq tier if it misses |
| **Job 2** — grounded explanation | Anthropic `claude-sonnet-5` | Sets the zero-hallucination outcome. Off the critical path — capability beats speed |

Job 2 config: **no sampling parameters** (Sonnet 5 rejects them), **no assistant prefill**; shape via `output_config.format`; **thinking set explicitly** at `effort: "low"` — omitting it runs adaptive thinking and lands on the first-audio budget. Both models pinned by **exact ID, never a `latest` alias**, or the 3-run CI guarantee is void. The two must remain different models. Two providers means two keys — Claude is not served by Groq.
- **TTS — Smallest.ai**, streaming playback.

### 5.2 Latency budget (p99)
Budgeted in two classes because they run on different providers. **Type A** = Groq only; **Type B** = retrieval + Anthropic.

| # | Stage | Target |
|---|---|---|
| L1 | Acknowledgment (both) — end-of-speech → transcript rendered + indicator | **<700 ms** |
| L2 | First audio — Type A | **≤1.5 s** |
| L3 | First audio — Type B | **≤2.5 s** |
| L4 | Shortlist rendered | **<3 s** |
| L5 | Explanation **text + citations rendered** (not audio end) | **≤6 s** |
| L6 | Booking confirm — both events created + code shown | **<5 s** |
| L7 | Cancel / reschedule | **<5 s** |
| L8 | PDF + email delivered | **<30 s** |

**Audio playback duration is never a target** — it scales with answer length, not system speed.

**Preconditions — the targets are void without these:** P1 warm process (Railway app sleeping **off**; no serverless in the pipeline; cold start measured separately) · P2 connection reuse (persistent Deepgram WebSocket, keep-alive pools) · P3 Deepgram endpointing **≤300 ms** (the dominant term inside L1) · P4 TTS starts on the first sentence · P5 OSM precomputed · P6 calendar writes issued in parallel · P7 Job 2 thinking configured explicitly.

**Measurement:** p99 over all suite runs + 20 timed interactions; hard failure at 2× any target; **per-component instrumentation** (STT-final, retrieval, LLM first/last token, TTS first byte, each API call) so a miss is diagnosable without a re-run. These are engineering targets, not measurements — a measured spike must confirm or openly renegotiate the table before the UI is built on it.

### 5.3 Security
Keys server-side only · HTTPS · **scraped text and RAG chunks are untrusted data**, delimited and never executed as instructions · no PII in logs or transcripts · **stateless demo**, no login, sessions isolated.

### 5.4 Deployment — Vercel (frontend) + Railway (backend)

| Tier | Holds | Never holds |
|---|---|---|
| **Vercel** | UI, card and citation view-models, mic client | **No keys, no provider calls, no API routes** |
| **Railway** | Whole pipeline, both LLM jobs, RAG index, precomputed OSM, calendar/Gmail, all keys | Nothing rendered directly to the tenant |

Every provider call originates on Railway — that is what makes "keys server-side only" true rather than aspirational. **No Vercel API routes**: serverless functions can't hold the persistent connections P2 needs and reintroduce the cost P1 excludes. Railway: app sleeping off, one long-lived process, healthcheck configured, **region chosen by measurement** (provider proximity usually beats user proximity; Smallest.ai being India-based may invert it). Cross-origin: **explicit CORS allowlist, never `*`**; mic WebSocket goes browser → Railway directly, never proxied; **contract version pinned, backend deployed first** — two hosts deploy independently, so production skew is possible with green CI.

Keys (all Railway env vars, none in Vercel, none in the repo): Deepgram · Groq · Anthropic · Smallest.ai · Google OAuth.

---

## 6. Error Handling

**Six governing principles** decide every case, including ones not yet written:

1. **Never fabricate to cover a failure** — "I don't have that" is always a correct answer.
2. **"Couldn't ask" and "nothing found" must never look alike** — one is a result, the other an error. Conflating them is the likeliest way this system misleads someone.
3. **Every failure is both spoken and shown.**
4. **No silent partial state** — completed, rolled back, or explicitly labelled incomplete.
5. **Fail fast at boot**, never mid-conversation.
6. **The tenant's intended state is authoritative**; reconcile external systems behind the scenes.

58 rows across seven groups. The ones most likely to be missed:

| Group | Notable cases |
|---|---|
| **6.A Audio & browser** | Mic permission denied · **TTS autoplay blocked** (fall back to full text + one-tap enable) · **barge-in** stops playback immediately · backgrounded tab is not end-of-speech · refresh loses the conversation but **a confirmed booking survives via its code** |
| **6.B STT** | Deepgram down as a *distinct* failure from the LLM · **locality spoken that was never scraped** — say so, never silently substitute · ambiguous amounts confirmed in words **and** digits |
| **6.C Understanding** | Question budget exhausted → proceed on what was confirmed, label the rest unknown · "the second one" re-anchored to **what the tenant last heard** · schema-invalid extraction never partially parsed |
| **6.D Grounding** | Index fails to load → **fail startup** · retrieval returning chunks that don't answer the question → declare the gap · injection inside a **RAG chunk**, not just listing text |
| **6.E Booking** | **Free/busy re-checked at confirm**, never trusted from offer time · concurrent sessions racing a slot · **all slot arithmetic in `Asia/Kolkata`** — the backend is deliberately outside India · the code is the only credential: rate-limited, unknown and cancelled codes answer identically |
| **6.F Delivery** | **Email address read back character by character before sending** — the highest-error input in the system · the **code is authoritative, not the PDF** |
| **6.G Infrastructure** | TTS down → turn completes in text · 429s reported as themselves · missing secret fails startup · combined failures degrade to the most conservative answer |

**Verification:** these are not extra eval cases. Each row is exercised or its guard shown in a documented walkthrough at sign-off; rows needing fault injection are labelled as such.

---

## 7. Evaluation

**Three suites × 20 cases = 60, 100% pass required, each suite run 3× in CI.** Determinism is configured per role: Job 1 at `temperature=0`; Job 2 has no sampling parameters, so repeatability rests on the pinned model ID plus structured output — which is why the 3-run rule matters rather than being a formality.

- **Suite A — Feasibility.** Budget, bedrooms, must-haves; boundary values; conflicts. Stratified across ≥3 localities, **≥1 case per schema field**, plus a `null`-handling case. Includes STT-normalisation cases.
- **Suite B — Edit correctness.** Untouched listings and their order **byte-identical** before/after.
- **Suite C — Grounding & hallucination.** Citations resolve to the correct listing-scoped source; gaps declared; injection case; **two cross-locality contamination probes** (adjacent and distant). Commute cases assert the method at **three layers — spoken, card badge, full label — and all three must name the same method**; disagreement fails even when each layer is well-formed. Asserted against the **view-model**, not pixels.

**Metrics:** latency per §5.2 scored per turn type · constraint match >98%, extraction >95%, ranking >90% · groundedness and citation correctness 100% · **zero observed hallucinations** across ~100+ claims · relevance ≥95%.

**Red lines (automatic failure):** any fabricated amenity/transit/number · **any distance or travel-time shown without its method, or with labels disagreeing between speech and card** · any citation not supporting its claim · any bare `[OSM]` · any cross-locality contamination · any PII surfacing.

**Sign-off** requires all of: 60 tests passing on 3 consecutive runs, zero red lines, three-layer view-model assertions, manual spot-check of 10 outputs per suite; latency met at p99 per turn type with no request over 2×, per-component timings recorded, cold start reported separately, **P1–P7 verified as actually in force**; plus published artefacts — locality list and counts, field-availability gap report, curation rule, pinned model IDs with Job 2's Suite C scores and effort setting, OSM precompute record, §6 walkthrough, and the deployment record (URLs, region and the measurements behind it, sleeping status, CORS allowlist).

---

## 8. Out of Scope (MVP)

Login/accounts · post-visit feedback · cross-session history · mobile app · languages beyond English · production-grade privacy compliance.

---

## 9. Implementation Sequence

*(Sequence, not a calendar.)*

1. **Scrape & curate** up to 10 listings per locality; **publish the locality list, counts and total**; document the availability marker or report the gap. First, because both the dataset size and the gap report can reshape everything downstream.
2. **Build the listing-scoped RAG index** (1–3 docs per locality) and **run the OSM query set once across every listing**, storing results with attribution and retrieval date; lock the commute-method disclosure.
3. **Voice pipeline** — Deepgram with keyterm boosting; Job 1 latency-verified; streaming TTS; **validate Job 2 against Suite C**; **run the measured latency spike and confirm or renegotiate §5.2 before the UI is built on it**.
4. **Shortlist logic**, refinement engine, grounded explanations with citations.
5. **Dual-calendar booking**, cancel/reschedule by code, PDF, Gmail — including the confirm-time free/busy re-check and IST-explicit slot arithmetic.
6. **UI** including the card and citation view-models Suite C asserts against. **Deploy Railway first, then Vercel.**
7. **Build the 60-test suites** + per-component instrumentation; publish the artefact list; iterate to sign-off.

---

*Open item, deliberately deferred: the locality list and total listing count are produced by step 1 and must be written back into §1 and §3.1 of the full document once the scrape completes.*
