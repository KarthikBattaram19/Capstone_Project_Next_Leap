# Voice-based AI Property Scout Platform – Bengaluru

*v3.10 — the current problem statement. Supersedes all earlier drafts; where this document and an earlier version disagree, this one governs.*

*Changed in v3.10 (§5.2): a new **L0** target for first visible feedback (<300 ms); **L3** tightened from ≤2.5 s to ≤1.5 s, made reachable by a new **P8** (fact-led opener); **P3** endpointing set to 400 ms with a new **P3b** content-aware hold, so speed is never bought by cutting a tenant off mid-sentence. L1 stays <700 ms. No other target moved.*

*Principal decisions: listing scope of **up to 10 per locality** with the locality set determined by the scrape (§1); an LLM **split into two roles across two providers** — Groq for extraction, Claude Sonnet for grounded explanation (§5.1); a latency budget **split by turn type** with explicit preconditions (§5.2); **commute-method disclosure** carried end-to-end from OSM precompute through card label to eval assertion (§3.4, §2.3, §4, §7.1); deployment on **Vercel (frontend) + Railway (backend)** (§5.4); and grouped, principle-driven error handling (§6).*

---

## 1. Problem Statement

Tenants don't struggle to find listings. They struggle to judge whether a listing actually fits their life: Is the commute realistic? Is the area safe at night? Is it worth the extra rent for the extra room?

**Solution:** A deployed, voice-first AI property scout that collects a tenant's spoken preferences, shortlists real listings, explains every shortlist decision with citations, and books a site visit on Google Calendar for both tenant and owner — with every neighborhood claim grounded in real data.

### Scope Constraints (Quality-First)
- One city: **Bengaluru** only
- **Up to 10 listings per locality**, scraped once from bengaluru.rent, cleaned and curated. A single 15-listing dataset was too thin to cover Bengaluru; breadth now comes from covering more localities, not from depth within one
- **The locality set is not pinned in advance.** It is whatever bengaluru.rent actually has available pins for. The final locality list and the resulting total listing count are an **output of the first deliverable (§9.1)**, documented after the scrape — not assumed here
- **"Up to" is a ceiling, not a target.** A locality with fewer than 10 available listings is kept at its real count and that count is documented; it is never padded with unavailable or duplicate pins. A locality with more than 10 is **curated down to the 10 best-populated records** (most fields present), and the selection rule is documented alongside the dataset so the shortlist is reproducible
- **Up to 3 neighborhood guide documents per *locality*** (not per listing). Listings in the same locality share the same documents, so the RAG corpus is **1–3 unique documents per locality** — at most 10 listings per document set

---

## 2. Core Capabilities (Required)

### 2.1 Voice-Based Preference Collection
Supports spoken inputs like: *"I'm looking for a 2BHK in Koramangala, budget 35k, need parking, close to a metro station."*

- Extracts: budget, bedrooms, must-haves, commute point, preferred areas
- Asks clarifying questions **only when required (max 5)**
- **Confirms all constraints verbally before generating the shortlist** — this is the system's primary defense against STT mishearing
- Language: **English only (MVP)**; Indian-English accents and vocabulary are in-scope (see §5.1)

### 2.2 Voice-Based Shortlist Refinement
- *"Drop anything above 40k."* / *"Only metro-adjacent."* / *"Add one with a balcony."*
- **Only the affected part of the shortlist changes**; unrelated listings and their order are preserved
- Refinements are cumulative — each edit applies on top of prior constraints
- Contradictory edits (e.g., "under 25k" after "only above 30k") trigger a clarifying question, not silent breakage

### 2.3 Explanation & Reasoning (Grounded)
Answers *"Why did you pick this one?"*, *"Is the commute realistic?"*, *"What's this area actually like?"*

- Every neighborhood claim cites its source; citations render in the UI
- Voice explanations may be short; the UI carries the full citation trail
- **Commute claims name the method that produced the number.** §3.4 now runs two methods, so "states its method" is only meaningful if the answer says *which*:

| Claim | Voice must say | UI label |
|---|---|---|
| Listing-anchored, routed — distance/time to nearest metro, bus stop, POI | "about a 14-minute walk **by route**" | `[OSM routing — precomputed <index date>]` |
| Listing-anchored, no routing available — straight-line fallback | "about 1.1 km **in a straight line**" | `[OSM straight-line — precomputed <index date>]` |
| Tenant's own commute point (§2.1) — the default | "roughly 6 km **straight-line** from where you said you work — the real road distance will be longer" | `[Straight-line from coordinates — computed now]` |
| Tenant's own commute point — where MCP routing was used instead | "about 32 minutes **by route**" | `[OSM routing — live]` |

  - **The words "straight line" or "by route" are mandatory in the spoken answer**, not optional polish. A bare "about 15 minutes to the metro" is a §7 red-line failure: it is unreproducible, and a straight-line figure spoken as if routed **understates a real Bengaluru commute badly enough to change a tenant's decision**
  - **Straight-line answers carry the caveat in the same breath**, never as a footnote the voice skips — per the standing rule that a limit is stated alongside the claim, not after it
  - The UI label additionally distinguishes **precomputed** from **computed now** (§3.4), so a reader can tell an index-date fact from a live one
  - **Suite C asserts this**: its commute-verification cases (§7.1) check that the stated method matches the method actually used *and* that the number is reproducible from it
- Missing data is declared, never papered over: "I don't have safety data for this area" is a correct answer

### 2.4 Site-Visit Booking (Dual Calendar)
- **Implementation:** one demo Google account holding **two secondary calendars — "Tenant" and "Owner"** — under a single OAuth authentication (fulfills the "single auth, two profiles" decision with minimum moving parts)
- **Slot inventory:** system queries the Owner calendar's free/busy for the **next 7 days, 10:00–18:00 IST, 1-hour slots**, and offers the first 3 free slots by voice; tenant picks or asks for others
- On confirmation, events are created on **both** calendars atomically (if either write fails, see §6.3)
- A **6-character alphanumeric confirmation code** is generated, shown in the UI, and included in the PDF — this code is the lookup key for cancel/reschedule (no login)
- **Cancel:** tenant states the confirmation code (voice or UI); system reads back slot + listing and requires explicit confirmation; on confirm, **both** calendar events are deleted atomically (if either delete fails, see §6.3). UI shows cancelled state; no new PDF
- **Reschedule:** tenant states the confirmation code; system offers free slots under the same inventory rules as booking (next 7 days, 10:00–18:00 IST, 1-hour, first 3 free, tenant may ask for others). On confirm, old events are deleted and new events created on **both** calendars atomically; **same confirmation code** is kept; a replacement PDF is generated and emailed (§2.5)
- Cancel and reschedule are refused if the original slot start time has already passed, or if the confirmation code is unknown
- A booking may be cancelled or rescheduled **more than once** until the visit starts (reschedule of an already-rescheduled booking uses the current slot)

### 2.5 PDF Generation & Email Delivery
- Generated **on-demand upon tenant confirmation**, sent immediately via Gmail as an attachment, then discarded — **no storage, no retention**
- Contents: shortlisted property details, location, visit date/time, confirmation code, owner contact
- Owner contact: **999999999 for all listings (demo placeholder — clearly labeled as such in the PDF)**. *Note: real Indian mobile numbers are 10 digits; this value is intentionally invalid to prevent accidental real-world dialing.*
- Recipient: tenant only

---

## 3. Data Requirements

### 3.1 Listings (bengaluru.rent)
- Scraped **once at deployment** → static dataset of **up to 10 listings per locality**; the total is at most 10 × (number of localities bengaluru.rent supports), fixed and documented at scrape time
- **Locality assignment:** every listing carries the locality it was scraped under, as a first-class field. This field drives RAG scoping (§3.3) and eval stratification (§7.1)
- **Availability filtering:** only pins marked currently available enter the working set; transparency-only pins ("Not for rent") are excluded. During scraping, the exact marker/field bengaluru.rent uses for this will be identified and documented; **if no reliable marker exists, that gap is reported before proceeding, not guessed around**
- **Fields (the searchable schema).** Every field below is filterable by voice and assertable in Suite A:

| Field | Type / values | Notes |
|---|---|---|
| `locality` | string | Per the locality bullet above; drives RAG scoping |
| `bhk_type` | enum: `1RK`, `1BHK`, `2BHK`, `3BHK`, `3BHK+` | The way tenants actually speak. Held **alongside** the raw `bedrooms` integer, not instead of it |
| `bedrooms` | integer | Raw count |
| `bathrooms` | integer | |
| `rent` | integer (Rs/month) | Base rent |
| `deposit` | integer (Rs) | Bengaluru deposits commonly run 5-10 months' rent; a stated budget means a very different thing at 2 months vs 10, so this is surfaced, not hidden |
| `maintenance_charges` | integer (Rs/month), plus whether it is included in rent or charged extra | |
| `property_type` | enum: `apartment`, `independent_house`, `villa`, `builder_floor` | |
| `furnishing` | enum: `unfurnished`, `semi_furnished`, `fully_furnished` | Pinned as an enum so filters are exact |
| `square_footage` | integer (sq ft) | Whether the source states carpet or built-up area is **recorded explicitly** at scrape time; the two are not interchangeable and must not be silently merged |
| `floor` / `total_floors` | integer / integer | |
| `lift` | boolean | |
| `parking` | enum: `two_wheeler`, `four_wheeler`, `both`, `none` | Split, not a single boolean - the distinction matters to tenants, and a bare "parking: yes" answers neither question |
| `amenities` | string list | Amenities **stated by the listing**. Distinct from nearby POIs, which come from OSM (§3.4) |
| `available_from` | date | Move-in date. Distinct from `availability_status` |
| `availability_status` | boolean flag | Per the availability and stale-listing bullets |
| `society_name` | string | |
| `coordinates` | lat, lng | |

- **Field confirmation is part of the first deliverable.** The schema above is what the system is built to search; **which of these fields bengaluru.rent actually publishes is confirmed at scrape time, not assumed here.** Any field the source does not carry is reported in the same gap report as the availability marker — never backfilled from model knowledge, OSM, or the RAG index (§3.5 admits no exception for listing facts)
- **Null is a real, displayable value.** A field the source does not state is `null`, and the system says *"not stated for this listing"*. It is never inferred, and never rendered as a default — a missing `deposit` is not ₹0
- **Null never silently satisfies a must-have.** If a tenant requires four-wheeler parking and some listings have `parking: null`, those listings are neither counted as matches nor silently dropped — they surface as a separate **"unknown on this filter"** group the tenant can choose to include. Without this rule, a wider schema makes the shortlist quietly *worse*, because every sparse field becomes an invisible filter
- **Budget filtering runs on `rent`** unless the tenant says otherwise; `deposit` and `maintenance_charges` are always **shown** on the card, so the real cost is never a surprise at booking
- **Deduplication:** listings merged when they share an exact address **or** coordinates within 50m; the most detailed record wins, merged records noted in dataset metadata
- **Stale-listing handling (corrected for static-scrape reality):** availability is a dataset flag. It can flip to unavailable via (a) an admin toggle simulating a delisting, or (b) an optional one-time recheck of the source pin at booking time. When a shortlisted listing goes unavailable, the system **removes it without requiring user action and immediately notifies the tenant**: "One listing in your shortlist is no longer available and has been removed."

### 3.2 PII
- Owner/agent names and phone numbers stripped **before** data touches the dataset, UI, logs, **or voice transcripts**
- The only contact value anywhere is the labeled demo placeholder (§2.5)

### 3.3 Neighborhood Guidance (RAG — Closed Index)
- **Pre-built closed index** created before deployment; no live fetching at query time
- Sources: Wikipedia neighborhood pages and comparable open city-guide sources, chunked with per-chunk source attribution
- Corpus: **1–3 unique documents per locality**, built once per locality and shared by that locality's ≤10 listings; each listing is mapped to its locality's documents at index time
- **Retrieval is listing-scoped:** queries about listing X retrieve only from the documents mapped to X's locality — this is the structural defense against cross-locality contamination (a Koramangala answer citing Indiranagar's document). Scaling to many localities makes this risk larger, not smaller, so it is tested explicitly (§7.1 Suite C)
- **Incomplete data:** show what exists + disclaimer "Limited neighborhood data available"; never fill gaps from model knowledge

### 3.4 Amenities & Transit (OpenStreetMap MCP — Precomputed)
- All amenity, transit-point, and POI claims come from the OpenStreetMap MCP (github.com/jagan-shanmugam/open-streetmap-mcp), queried around each listing's coordinates
- **Precomputed at index time, not at query time.** Every listing-anchored OSM fact is resolved once during §9.3 and stored on the listing record. **No OSM call is made inside a tenant's turn.** This mirrors §3.3's closed RAG index: the same "resolve once, serve from local storage" discipline, for the same reason
  - **Why:** these facts are static — a metro station does not move between turns — and a live per-listing lookup across a shortlist would exhaust §5.2's L4 budget on network round trips alone (see §5.2 P5)
  - **Grounding is unaffected.** OSM remains the sole permitted source for these claims (§3.5); only the *timing* of the lookup moves. Each stored value keeps its OSM attribution **and the date it was retrieved**, so the UI cites OSM exactly as it would have live
- **The precomputed query set is fixed and documented** — the same queries run for every listing, so coverage is uniform and no listing looks richer merely because it was queried more. Where OSM returns nothing for a listing, the value is stored as `null` and §3.1's null rules apply verbatim: "not stated", never inferred, never silently treated as a match
- **Two claim types, two timings — the distinction matters:**

| Claim | When computed | Method |
|---|---|---|
| **Listing-anchored** — nearest metro/bus stop, distance to it, nearby amenities and POIs | **Index time** (precomputed, stored) | OSM MCP, per the fixed query set |
| **Tenant-specific commute** — listing → the commute point the tenant states in §2.1 | **Query time** (the destination is not known until the tenant speaks, so it cannot be precomputed) | **Default: straight-line distance from the stored coordinates — pure local arithmetic, no network call, no latency cost.** MCP routing may be used instead only if it fits §5.2's budget; whichever was used is disclosed |

- **Commute/travel-time method (must be disclosed in UI):** use the MCP's routing/directions capability where available; otherwise fall back to a stated straight-line-distance heuristic (e.g., "~1.1 km from the metro, roughly a 14-minute walk"). A claim like "within 15 minutes of a metro station" must be reproducible from the disclosed method — **and the disclosure must name which of the two methods produced that specific number**, since both are in use
- **Staleness:** precomputed OSM values are exactly as static as the scraped dataset (§3.1) and carry the same caveat — they reflect OSM as of the index date shown, not live conditions
- MCP integration lives in the **orchestration layer** and runs during the **build step**; ranking/shortlist logic lives in application code and reads the stored values

### 3.5 Grounding Boundary (resolving the original brief's ambiguity)
| Claim type | Sole permitted source |
|---|---|
| Listing facts (every field in §3.1's schema — rent, deposit, maintenance, BHK, furnishing, area, floor, parking, availability, move-in date) | Scraped bengaluru.rent dataset. **No fallback source:** an absent field is `null`, never filled from OSM, RAG, or model knowledge |
| Amenities, transit points, distances | OpenStreetMap MCP — **precomputed at index time** (§3.4); attribution and permitted-source status unchanged by the precompute |
| Neighborhood character, safety notes, "what it's like" | Closed RAG index, with citation |
| Anything else | Not asserted. Declared as unavailable |

---

## 4. Companion UI (Desktop-First Web App, 1024px+)

Futuristic real-estate theme. Required components:
- **Shortlist cards** — **locality shown as the card's primary label** (with society name beneath it where stated), rent, **deposit and maintenance** (so total cost is visible up front), BHK type, size in sq ft, floor, parking, furnishing, key amenities; fields the source didn't state render as *"not stated"*, never blank and never zero; expandable
  - With up to 10 listings per locality (§1), a shortlist will routinely span several localities — **locality is what makes two otherwise-identical 2BHKs distinguishable at a glance**, so it is not buried in the expanded view
  - **Cards are grouped by locality**, with the locality name as the group heading and its listing count beside it; within a group, ranking order is preserved. Grouping is presentation only — it must not reorder the shortlist itself, which §2.2 and Suite B require to stay stable across voice edits
  - The word **"area" is avoided in card labels** — it reads as both locality and floor size. Locality is labeled *locality*; floor size is labeled *sq ft*
  - **Commute lines carry their method label (§2.3).** Each card shows up to two commute rows, and **neither may display a number without its method** — an unlabelled distance on a card is the same red-line failure as an unlabelled one in speech:

    | Row | Shown when | Card format |
    |---|---|---|
    | **Nearest transit** | Always (listing-anchored, §3.4) | `Metro · 1.1 km · by route` or `Metro · 1.1 km · straight-line` |
    | **Your commute** | Only when the tenant stated a commute point (§2.1) | `Work · ~6 km · straight-line` |

    - **Two-tier labelling, so the card stays readable without losing provenance:** the card carries the short method badge (`by route` / `straight-line`); the **full label with its precomputed-or-live status and index date** — `[OSM routing — precomputed <date>]`, `[Straight-line from coordinates — computed now]` — appears in the expanded view, the neighborhood snapshot panel, and the Sources section. **The badge is never dropped to save space**; if the card is too tight for it, the number comes off the card, not the label
    - **`straight-line` badges are visually distinct** (not merely different text) so a scanning tenant does not read an as-the-crow-flies figure as a real travel time
    - Where OSM returned nothing for a listing, the row reads **"not stated"** per §3.1's null rules — never a blank row, never `0 km`
    - No commute point stated means **the "Your commute" row is absent**, not empty
- **Neighborhood snapshot panel** per listing — transit, safety notes, amenities, each with its citation. Transit and distance entries carry the **full commute-method label** (method + precomputed-vs-live + index date), of which the card shows only the short badge
- **Microphone button + live transcript** — visible partial transcription while speaking; clear recording/listening/processing states
- **Sources/References section** — where every claim came from, e.g., `[Wikipedia — Koramangala]`, `[OSM routing — precomputed 2026-09-01]`, `[Straight-line from coordinates — computed now]`. **A bare `[OSM]` is not sufficient** once §3.4 runs two methods at two different times: the entry must resolve to the method and the moment that produced the number
- **Visit-confirmation panel** — slot, time, confirmation code, PDF status, and actions to **cancel** or **reschedule** (code entry if the panel is no longer showing the active booking)
- **Empty state (zero results)** — names the unmet constraints and suggests specific relaxations ("Nothing under 25k in Koramangala — try 30k, or nearby HSR Layout"); user adjusts manually, system never auto-relaxes

---

## 5. Technical Architecture

### 5.1 Voice Pipeline
- **STT:** Deepgram — **required configuration:** keyterm/keyword boosting for **every locality name in the final scraped set** (Koramangala, Indiranagar, HSR Layout, Whitefield, Marathahalli, BTM Layout, and whatever else the scrape yields — the keyterm list is generated from the dataset's locality field, not hand-written) and normalization of Indian-English amounts ("35k" → 35000; "1.2 lakh" → 120000). *This is the single most likely real-world failure mode; it is a first-class requirement, not a polish item.*
- **LLM: two models from two providers, because the two jobs have opposite requirements.** Job 1 runs on **Groq** for speed; Job 2 runs on **Anthropic's Claude Sonnet** for grounding discipline. Structured (JSON) outputs everywhere, so evals assert on fields rather than prose; `temperature=0` on Job 1. *This means two vendors and two API keys — Claude models are not served by Groq. The tradeoff is deliberate: the second key buys the model that decides whether §7.2's zero-hallucination bar is met.*

| Role | Model | What it does | Why this model |
|---|---|---|---|
| **Job 1 — Extraction & edit routing** (§2.1, §2.2) | **Groq `openai/gpt-oss-120b`** | Speech → structured constraint record (`{bhk_type, locality, rent_max, parking, …}`); applies voice edits as field-level changes | Groq's inference speed is what makes the 700 ms acknowledgment and ≤1.5 s first-audio budgets (§5.2) achievable at all. The task needs schema conformance, not reasoning — so this role is chosen on latency, and the choice is **validated against §5.2 at p99 before being locked** (see the Job 1 latency check below) |
| **Job 2 — Grounded explanation** (§2.3) | **Claude Sonnet — model ID `claude-sonnet-5`** (Anthropic API) | Listing record + retrieved chunks → answer with citations; declares gaps instead of filling them; ignores instructions embedded in scraped text (§5.3) | This is where the zero-hallucination bar (§7.2) is won or lost. Chosen for citation discipline, willingness to state that a source does not cover something, and resistance to instructions embedded in untrusted data. It is **off the critical latency path** — TTS is already speaking — so capability is worth more than speed here |

- **Job 1 latency check:** `gpt-oss-120b` is a large model carrying a latency-critical role. **Measure it against §5.2's acknowledgment and first-audio targets at p99 before locking it.** If it misses, drop to a lighter Groq model for this role (e.g. the `gpt-oss-20b` tier or a small Qwen/Llama variant) — Job 1 only has to emit valid JSON, so trading capability for speed here costs nothing that §7 measures
- **Job 2 configuration:** `temperature` is **not** set — Claude Sonnet 5 does not accept sampling parameters, and a request carrying one is rejected. Determinism for §7's CI runs comes from the pinned model ID plus structured output, not from a temperature value. Fix the response shape with structured outputs (`output_config.format`); **assistant prefill is not supported on this model**, so it cannot be used to force a format. **Thinking must be set explicitly** — omitting it runs adaptive thinking at default effort, which lands on the §5.2 L3 budget; start at `output_config: {effort: "low"}` (see §5.2 P7)
- **Job 2 still has to earn the role.** Validate it against Suite C before locking, and record the scores in the repo. If a Groq-hosted model reaches the same Suite C result, collapsing back to a single vendor is a legitimate simplification — the two-key setup is justified by measured grounding quality, not by brand
- **Job 1 and Job 2 must remain different models**, so that a model chosen for speed never sets the grounding bar
- **Both models are pinned by exact model ID, never by a `latest`-style alias.** §7's "3 consecutive CI runs at 100%" is only meaningful if the model under test cannot change underneath the suite; an alias that silently re-points invalidates every prior run
- **Cost/latency note:** Job 2 runs once per explanation request, not once per turn, so the more expensive model is invoked far less often than Job 1's. Claude Sonnet 5 is billed per token — **confirm current pricing on Anthropic's pricing page before budgeting**; this document does not track it
- **TTS:** Smallest.ai, streaming playback (audio starts before full synthesis completes)

### 5.2 Latency Budget (precise definitions)

**Turns are budgeted in two classes, because they run on different providers (§5.1).**
**Type A** — preference collection, refinement, booking, cancel/reschedule — uses Job 1 on Groq only.
**Type B** — grounded explanation — uses RAG retrieval plus Job 2 on the Anthropic API, a second provider on a second network path. Both classes now share a 1.5 s first-audio budget, but for different reasons: Type A waits on Job 1; Type B does not wait on Job 2 at all, because its first sentence is built by code from facts already resolved (P8).

| # | Stage | Target (p99) | Definition | What dominates the budget |
|---|---|---|---|---|
| L0 | **First feedback** (both types) | **<300 ms** | A word spoken → that word visible in the live transcript, with the listening state shown | Deepgram interim-result latency plus one network hop. **Independent of end-of-speech**, so it has no cut-off cost — this is the number that makes the system *feel* instant |
| L1 | **Acknowledgment** (both types) | **<700 ms** | End-of-speech → final transcript rendered **and** processing indicator visible | Deepgram's endpointing silence window (see P3) plus one network hop. Nothing else fits in this budget — no LLM call may sit inside it. **Bounded below by P3:** the system cannot know speech has ended before the silence window has elapsed, so L1 is never traded down by shortening that window |
| L2 | **First audio — Type A** | **≤1.5 s** | End-of-speech → first TTS audio byte plays | L1 + Job 1 round trip + TTS time-to-first-byte |
| L3 | **First audio — Type B** | **≤1.5 s** | End-of-speech → first TTS audio byte plays | L1 + retrieval + a **code-built opener from facts already resolved (P8)** + TTS. Job 2's cross-provider first token no longer sits inside this budget. **Without P8 the honest figure is 2.5 s** (L1 + retrieval + Job 2 time-to-first-token + TTS) — which is why P8 is a precondition, not a nicety |
| L4 | **Shortlist rendered** | **<3 s** | End-of-speech → full shortlist rendered in the UI | Job 1 extraction. Filtering itself is application code over a few hundred records — microseconds — **provided P5 holds**. Tightened from 5 s because no LLM performs the filtering |
| L5 | **Explanation rendered** | **≤6 s** | Question end → **full explanation text and its citations rendered in the UI**. Explicitly **not** the end of audio playback | Job 2 generation length. Loosened from 4 s: cross-provider generation with citations cannot be held to a budget written for local Groq inference |
| L6 | **Booking confirm** | **<5 s** | Confirmation utterance → both calendar events created + code shown | Two Google Calendar writes (**issued in parallel**, per P6) |
| L7 | **Cancel / reschedule** | **<5 s** | Confirmation utterance → both calendars updated + UI state shown | Reschedule is **four** calendar calls (2 deletes + 2 inserts); parallelism is what keeps this inside 5 s, not optional tuning. Reschedule's PDF+email uses L8 |
| L8 | **PDF + email** | **<30 s** | Booking **or** reschedule confirmed → email delivered | Gmail send; off the interactive path |

**Audio playback duration is never a latency target.** How long the tenant listens is a function of answer length, not system speed; a 90-word explanation takes ~35 s to speak however fast the stack is. Every target above ends at *first byte* or *rendered*, never at "finished speaking."

#### Preconditions — the targets are void without these
These are not tuning tips. Each one, if skipped, breaks a specific row above.

- **P1 — Warm process.** Budgets assume an already-warm server. A host that sleeps adds 10–30 s to the first request and would fail every row — concretely, **Railway app sleeping must be off** (§5.4), and no part of the pipeline may run as a Vercel serverless function. Either that, or a keep-warm ping, stated as such; **measure and report cold start separately**, never inside these numbers
- **P2 — Connection reuse.** Persistent WebSocket to Deepgram; HTTP keep-alive to Groq, Anthropic, Google and Smallest.ai. A fresh TLS handshake per call adds roughly a round trip each and L2 has no room for it
- **P3 — Deepgram endpointing 400 ms.** The silence window before a transcript is finalized is the largest single term inside L1 and is a configured value, not a given. Set it explicitly. **It is a floor as much as a ceiling:** natural mid-sentence pauses — before a number, before a locality name — run roughly 200–500 ms, and a window inside that range cuts tenants off; a window far above it wastes L1. 400 ms with P3b is the balance. Gate L records the false end-of-speech rate to confirm it on real Indian-English speech, which is where this figure has not yet been measured
- **P3b — Content-aware hold.** If the interim transcript ends in a continuation word (*under, above, near, with, and, about, around, to*) or a bare number without a unit, the orchestrator waits up to a further 400 ms before treating the silence as end-of-speech. Plain pattern matching, no model. A hard fallback — Deepgram's utterance-end event at about 1 s — guarantees nobody waits indefinitely. This is what protects "two BHK… under forty thousand" from being finalized after "BHK"
- **P4 — TTS starts on the first sentence,** not on the complete response text. L2 and L3 are first-byte budgets and are unreachable if synthesis waits for the full string
- **P5 — OSM facts are precomputed at index time,** not fetched per query. Amenity and transit values for each listing are resolved once during §9.3 and stored on the record; **OSM remains the sole source and the attribution is unchanged (§3.5)** — only the timing moves. Live per-listing OSM calls inside a shortlist turn would put L4 out of reach on its own
- **P6 — Calendar writes issued in parallel.** Sequential round trips make L6/L7 depend on Google's latency multiplied by the number of calls. §2.4's atomicity requirement is about the *outcome* and does not require sequential requests
- **P7 — Job 2 thinking is configured explicitly.** Claude Sonnet 5 runs **adaptive thinking by default when `thinking` is omitted**, at default effort — thinking tokens are produced before any visible text, which lands directly on L3. Set `output_config: {effort: "low"}` (raise only if Suite C scores require it) and measure L3 and L5 at that setting. Prefer lowering effort to disabling thinking outright; grounded citation work is retrieval-bound rather than reasoning-bound, so low effort is the expected operating point
- **P8 — Fact-led opener on Type B.** The first sentence spoken on an explanation turn is produced by **application code from facts already resolved** — rent, BHK, the commute distance with its method label — while Job 2 streams behind it. Every word is a §3.5-grounded value and no model touches the opener, so §3.5 and the commute-disclosure rule hold exactly. This is what removes Job 2's cross-provider first token from L3; L5 (checked text and citations rendered) is unchanged

#### Measurement rules
- **All targets are p99**, measured over the §7.2 sample: every suite run plus the 20 dedicated timed interactions. p99 over a handful of manual tries is not a measurement
- **Hard failure if any single request exceeds 2× its row's target**
- **Instrument per component, not just per turn** — record STT-interim (for L0), STT-final, retrieval, LLM first-token, LLM last-token, TTS first-byte, and each external API call separately. A turn that misses its budget must be diagnosable to a stage without re-running it
- **These numbers are engineering targets derived from the architecture, not measurements.** §9.2's Gate L requires a measured latency spike, on deployed infrastructure, before anything is built on these numbers; **if a row proves unreachable, it is renegotiated openly and this table is updated — the failure mode to avoid is a budget quietly ignored because it was never achievable**

### 5.3 Security & Robustness
- All API keys server-side only; never exposed to the frontend
- HTTPS on the deployed URL
- **Prompt-injection defense:** scraped listing text and RAG chunks are untrusted *data* — delimited in prompts and never interpreted as instructions; a listing description saying "ignore previous instructions" must have no effect
- No PII in logs or stored transcripts (per §3.2)
- Session model: **stateless demo** — no login, no persistence, each session isolated

### 5.4 Deployment

- Git version control (public repo), deployed prototype at a public URL
- **Frontend → Vercel. Backend → Railway.** Two origins, one contract between them

| Tier | Host | Holds | Never holds |
|---|---|---|---|
| **Frontend** | Vercel | §4's UI, the card and citation view-models, the mic capture client | **No API keys. No provider calls. No API routes.** |
| **Backend** | Railway | The whole voice pipeline, both LLM jobs, RAG index, precomputed OSM values, calendar/Gmail integration, all four provider keys | Nothing rendered directly to the tenant |

**The split is a hard boundary, not a convenience.** Every provider call originates on Railway. The browser talks to exactly one backend origin and to no provider directly — that is what keeps §5.3's "keys server-side only" true rather than aspirational.

**Why no Vercel API routes, even for "just one endpoint":**
- Vercel's functions are **serverless and per-invocation**. They cannot hold the persistent Deepgram WebSocket or the pooled keep-alive connections §5.2 P2 requires, and each cold invocation reintroduces exactly the startup cost P1 exists to exclude
- A long-lived audio stream needs a long-lived process. Railway runs one; a serverless function does not
- Splitting provider calls across two hosts would put keys in two places and make §5.2's per-component timings unattributable

**Railway configuration (each item maps to a §5.2 precondition):**
- **App sleeping must be OFF** — a sleeping instance wakes on the tenant's first word and blows every row in §5.2. If the chosen plan can sleep, either move off it or run a keep-warm ping, and **say which was done in the §7.3 report** (P1)
- **One long-lived process**, holding the Deepgram WebSocket and keep-alive pools to Groq, Anthropic, Google and Smallest.ai (P2)
- **Healthcheck endpoint** configured so a failed deploy is caught by Railway rather than by a tenant
- **Region is chosen by measurement, not by intuition.** The backend makes many round trips to the providers per turn but holds only one stream to the browser, so **proximity to the providers usually matters more than proximity to Bengaluru** — but Smallest.ai is India-based and may invert that. Time both a US region and the Singapore region during §9.2's latency spike and pick on the numbers; **record the chosen region in the §7.3 report.** Confirm Railway's current region list in their docs rather than assuming this one

**Vercel configuration:**
- **Static/SSR frontend only.** Its sole backend-related environment variable is the Railway backend URL — a public value, not a secret
- **Preview deployments create new origins.** Either add them to the CORS allowlist deliberately or restrict the backend to the production origin; **an accidentally open allowlist is a security finding, not a convenience**

**Cross-origin contract:**
- **CORS allowlist is explicit** — the Vercel production origin (plus any previews deliberately included). Never `*`
- **WebSocket (browser → Railway) carries the mic audio.** It is not proxied through Vercel; a proxy hop would add a round trip inside §5.2 L1, which has no room for one
- **Backend exposes a contract version**, and the frontend pins the version it expects. Two hosts deploy independently, so **version skew is possible in production even when CI is green** — Suite C's view-model assertions run against a matched pair and would not catch a mismatched one. **Deploy backend first, frontend second**
- Both tiers are HTTPS by default on these hosts, satisfying §5.3

**API keys — all four set as Railway environment variables, none in Vercel, none in the repo:** Deepgram (deepgram.com) · **Groq — Job 1** (console.groq.com/keys) · **Anthropic — Job 2** (console.anthropic.com) · Smallest.ai (app.smallest.ai/dashboard), plus the Google OAuth credential for §2.4's calendars.

---

## 6. Error Handling & Edge Scenarios

**Row IDs are stable identifiers, not an ordering.** 6.1–6.12 keep the numbers they were assigned in earlier versions because other sections cite them; new rows are appended within the group they belong to. Read the groups, not the sequence.

### 6.0 Governing principles — these decide every row below, including ones not yet written

1. **Never fabricate to cover a failure.** "I don't have that" is a correct answer everywhere in this system. A degraded answer that sounds complete is worse than an admitted gap, and is a §7.2 red line
2. **"Couldn't ask" and "nothing found" are different answers and must never look alike.** An empty shortlist because the tenant's constraints matched nothing is a *result*; an empty shortlist because a service failed is an *error*. Rendering them identically is the single most likely way this system misleads someone
3. **Every failure is both spoken and shown.** Voice-only leaves no trace to read; UI-only is invisible to someone listening
4. **No silent partial state.** Anything half-done is either completed, rolled back, or explicitly labelled as half-done with what is missing
5. **Fail fast at boot, not at the tenant's first word.** Missing config, unloadable dataset or unreachable index must stop startup — never surface as a mid-conversation error
6. **The tenant's intended state is authoritative.** Where an external system disagrees or is unreachable, record the intent, tell the tenant plainly, and reconcile behind the scenes (§6.3)

### 6.A Microphone, audio & browser session

| # | Scenario | Behavior |
|---|---|---|
| 6.13 | Mic permission denied or blocked by browser policy | State it in the UI with recovery steps for that browser; the app remains usable by typing. **Never fail silently into a dead mic button** — the tenant will assume the system is broken, not the permission |
| 6.14 | No input device, or device disconnected mid-session | Detect and say so immediately; preserve the conversation state so it resumes when a device returns |
| 6.15 | TTS playback blocked by browser autoplay policy | Audio playback is armed by the tenant's own click on the mic control — that gesture is the unlock. If playback is still refused, **the full response renders as text** and the UI offers a one-tap "enable voice". Silence with no explanation is not acceptable |
| 6.16 | Tab backgrounded or audio context suspended mid-turn | Pause capture, hold state, resume on return. Do not treat suspension as end-of-speech — that would fire §5.2 L1 against a truncated utterance |
| 6.17 | **Barge-in** — tenant speaks while TTS is playing | Stop playback immediately and capture the new utterance. The tenant interrupting is a deliberate act, not noise; talking over them is the fastest way to make the demo feel broken |
| 6.18 | Silence, or an utterance with no words | Re-prompt once with a concrete example; do not send an empty transcript to Job 1 |
| 6.19 | Runaway utterance (no end-of-speech detected) | Cap capture at a stated maximum, transcribe what was captured, and confirm the extracted constraints back before acting (§2.1) |
| 6.20 | Non-speech audio, heavy background noise, or another speaker | Treated as low confidence (§6.6): confirm rather than proceed. Never guess a locality or amount from a noisy transcript |
| 6.21 | Page refresh or tab close mid-conversation | The session is stateless by design (§5.3): conversation state is lost and the UI says so on reload. **A booking already confirmed survives** — it lives in the calendars and is reachable by its confirmation code (§2.4). A booking mid-flow but unconfirmed does not exist and must not be implied to |
| 6.22 | The same tenant opens a second tab | Sessions are independent (§5.3). The second tab does not inherit or corrupt the first; a confirmation code entered in either resolves the same booking |

### 6.B Speech recognition

| # | Scenario | Behavior |
|---|---|---|
| 6.6 | STT low-confidence on a critical field (budget, locality) | Read back and confirm that field specifically before proceeding |
| 6.23 | Deepgram unavailable, rate-limited, or the WebSocket drops mid-utterance | Reconnect once transparently. If capture was interrupted, **say what was lost and ask for it again** — never transcribe a partial utterance and act on it. This is a distinct failure from §6.11; the tenant is told which capability is down, not a generic error |
| 6.24 | Locality spoken that is **not in the scraped set** (another Bengaluru area, or another city) | Say plainly that this locality is not covered and name what is, offering the nearest covered locality. **Never silently substitute a different locality** — that is a §3.5 grounding violation wearing a UX costume |
| 6.25 | Speech in another language, or English code-switched with Kannada/Hindi terms | English-only is the stated MVP scope (§2.1). Say so rather than transcribing into nonsense; if a locality name survives recognisably, confirm it explicitly before use |
| 6.26 | Ambiguous amount — "thirty five", "3.5", "one point two" | Ambiguity between 35 / 35,000 / 3.5 lakh is resolved by asking, never by assuming a magnitude. Confirmed back in words **and** digits ("thirty-five thousand — ₹35,000") |

### 6.C Understanding, scope & conversation

| # | Scenario | Behavior |
|---|---|---|
| 6.5 | Contradictory voice edit | Clarifying question, not silent failure |
| 6.27 | Constraint that no listing could satisfy (₹5,000 budget, 6BHK) | Handled as §6.1 zero-results — name the binding constraint specifically. The system never auto-relaxes |
| 6.28 | Out-of-scope request — buying, PG/hostel, roommates, commercial space, another city | Say what the system does and does not cover, in one sentence, and return to the task. Do not improvise an answer from model knowledge |
| 6.29 | Clarifying-question budget (max 5, §2.1) exhausted with constraints still unclear | Proceed on what **was** confirmed, state explicitly which constraints are being applied and which are unknown, and show the result as provisional. Silently inventing the remainder is forbidden |
| 6.30 | Ambiguous reference — "the second one", "that one" — after the list changed | Re-anchor by naming the listing ("the 2BHK in HSR Layout at ₹32,000?") and confirm before acting. Position-based references are resolved against **what the tenant last heard**, not the current internal order |
| 6.31 | No constraints given at all — "just show me something" | Ask for the one or two constraints that most reduce the set (budget, locality). Do not return an arbitrary slice and present it as a shortlist |
| 6.32 | Job 1 returns output that violates the schema despite structured output | Retry once; on a second failure, treat as §6.11 Job 1 down. **Never partially parse a malformed record** — a half-read constraint set produces a confidently wrong shortlist |
| 6.33 | Tenant asks for the owner's name or number | Only the labelled demo placeholder exists (§2.5, §3.2); say so. No real contact data exists anywhere in the system to disclose |
| 6.34 | Off-topic, abusive, or prompt-injection-style input from the **tenant** | Decline briefly and return to the task. Tenant speech is instruction, but it cannot override §3.5's grounding boundary or reveal system configuration |

### 6.D Data, grounding & retrieval

| # | Scenario | Behavior |
|---|---|---|
| 6.1 | Zero results | Empty state + specific relaxation suggestions; no auto-relaxing |
| 6.2 | Missing neighborhood data | Partial info + "Limited neighborhood data available" disclaimer |
| 6.4 | Listing goes unavailable post-shortlist | Remove without user action + notify tenant (§3.1) |
| 6.8 | Injection content in scraped data | Neutralized by §5.3; covered by a grounding-suite test |
| 6.35 | Dataset, RAG index, or precomputed OSM values fail to load at startup | **Fail startup** (principle 5). A backend that serves a tenant from a half-loaded index will answer confidently from whatever it did load |
| 6.36 | Retrieval returns chunks, but none actually support the question asked | Declare the gap (§6.2 wording). Retrieving something is not the same as having an answer, and this is exactly where a fluent model invents one |
| 6.37 | Injection content inside a **RAG chunk** (as distinct from a listing field) | Same treatment as §6.8 — both are untrusted data under §5.3. Called out separately because the defence is often applied only to listing text |
| 6.38 | OSM returned nothing for a listing's transit or amenity query | Row reads "not stated" (§3.1 null rules, §4). Never blank, never `0 km`, never filled from another listing's values |
| 6.39 | **Every** shortlisted listing becomes unavailable | Say so directly and return to constraint collection. Do not silently backfill from outside the shortlist — the tenant would receive listings they never saw chosen |

### 6.E Booking, cancel & reschedule

| # | Scenario | Behavior |
|---|---|---|
| 6.3 | Calendar API down / write or delete fails | Accept the intended state (booked / cancelled / rescheduled), show code, queue calendar sync for retry; if only one of the two calendar writes/deletes succeeded, retry the other — never leave a half-booking or half-cancel silently |
| 6.9 | Unknown or already-cancelled confirmation code | State that no matching visit was found; do not invent a booking |
| 6.10 | Cancel/reschedule after slot start | Refuse; state that the visit time has already started |
| 6.40 | No free slots anywhere in the 7-day window | Say so explicitly and offer the earliest slot beyond the window, or to try another listing. An empty slot list is never presented as "pick one" |
| 6.41 | Offered slot is taken between the offer and the confirmation | **Free/busy is re-checked at confirm, not trusted from offer time.** On a clash, say so and offer the next free slots. The window between offering and confirming is exactly long enough for this to happen |
| 6.42 | Two concurrent sessions confirm the same slot | The re-check in §6.41 is the guard; the second confirmation loses and is re-offered. **Neither tenant is told a booking exists that does not** |
| 6.43 | Listing becomes unavailable between shortlist and booking confirmation | Booking is refused with the reason given (§3.1's optional booking-time recheck). Confirming a visit to a delisted property is worse than refusing it |
| 6.44 | Confirmation-code collision on generation | Generated codes are checked for collision against live bookings before being issued; a collision regenerates rather than overwrites |
| 6.45 | Someone enters a code that is not theirs, or guesses codes | There is no login (§8), so **the code is the only credential**. Lookups are rate-limited, and the response to an unknown code is identical to the response for a valid-but-cancelled one (§6.9), so the endpoint cannot be used to enumerate live bookings. *Stated as a demo-scope limitation, not solved: a code alone is weak authorisation, acceptable only because the calendars hold no real personal data (§3.2)* |
| 6.46 | Google OAuth token expired or revoked mid-session | Treated as §6.3 — the intended state stands, the tenant is told the calendar is temporarily unreachable, and re-auth is an operator action, never something the tenant is asked to perform |
| 6.47 | **Server timezone is not IST** | All slot arithmetic uses `Asia/Kolkata` explicitly — never the server's local time. **The backend region is chosen by measurement (§5.4) and will likely not be in India**, so any reliance on server-local time is a live bug waiting for the demo. Slot boundaries, the 7-day window, and §6.10's "already started" check all evaluate in IST |
| 6.48 | Tenant asks for a slot outside 10:00–18:00 IST or beyond 7 days | State the inventory rule (§2.4) and offer what exists |
| 6.49 | Reschedule requested to the slot already held | Confirm that nothing changed rather than deleting and recreating the same events; the code and PDF stand |

### 6.F PDF & email delivery

| # | Scenario | Behavior |
|---|---|---|
| 6.7 | Email send fails | Booking stands; UI offers PDF download + retry email |
| 6.50 | Email address misheard, malformed, or never provided | **The address is confirmed by reading it back character by character before any send** — spelling an address by voice is among the highest-error inputs in the whole system. On failure the booking still stands and the PDF is offered for download (§6.7); delivery is never a precondition for the visit existing |
| 6.51 | PDF generation fails | Booking stands and is shown with its code; the PDF is offered for retry. **The confirmation code is authoritative, not the document** |
| 6.52 | Repeated resend requests, or Gmail rate limiting | Rate-limit resends per booking and say plainly when the limit is hit |

### 6.G Providers, infrastructure & deployment

| # | Scenario | Behavior |
|---|---|---|
| 6.11 | LLM unavailable, rate-limited, or times out | **Job 1 (Groq) down** — the turn cannot proceed; say so plainly ("I didn't catch that, one moment") and retry once, then ask the tenant to repeat. Never guess the constraints from a partial transcript. **Job 2 (Anthropic) down** — the shortlist still renders (it is produced by application code, not the LLM); the explanation is withheld with "I can't explain this one right now", never substituted with an ungrounded answer. Falling back from Job 2's model to Job 1's for explanations is **not permitted**, since the grounding bar is model-dependent. *Upside of the two-provider split: Groq and Anthropic fail independently, so one provider's outage degrades a single capability rather than taking the whole demo down* |
| 6.12 | Backend unreachable from the frontend — Railway down, CORS rejection, or frontend/backend version skew (§5.4) | The UI states plainly that it cannot reach the service and offers retry. **It never renders an empty shortlist, a zero result, or a silent partial state** — "nothing found" and "couldn't ask" are different answers and must not look alike. A detected contract-version mismatch names itself as such rather than failing as a generic error |
| 6.53 | **TTS (Smallest.ai) unavailable** | The turn completes in text — shortlist, explanation and citations all render — with the UI stating that voice output is temporarily unavailable. Losing the voice must not lose the answer |
| 6.54 | Any provider returns 429 / quota exhausted | Retry once with backoff inside the turn's budget; beyond that, the row for that provider applies (§6.11, §6.23, §6.53). **Quota exhaustion is reported as itself**, not disguised as an empty result |
| 6.55 | A required secret or environment variable is missing or invalid at deploy | **Startup fails loudly** (principle 5). A missing key must never be discovered by a tenant mid-sentence — the §5.4 healthcheck is what surfaces it |
| 6.56 | Cold start on the first request after idle | Excluded from §5.2 by P1 and prevented by §5.4's configuration; if it occurs, it is measured and reported (§7.3), never averaged away |
| 6.57 | Concurrent tenants beyond one backend process | Provider rate limits, not CPU, bind first. Demo scope: state the concurrency actually tested in the §7.3 report rather than implying it is unbounded |
| 6.58 | **Two failures at once** (e.g. Job 2 down *and* neighborhood data missing) | Report the failure closest to the tenant's actual question, and never let one failure's message imply the other subsystem succeeded. Combined failures degrade to the most conservative response available, which is always "I can't answer that right now" |

### 6.H Verification

The rows above are **not** additional eval cases — §7.1 stays at 60 tests. They are verified by a **documented walkthrough at sign-off**: each row is exercised or its guard shown in code, and the result recorded in the §7.3 report. A row that cannot be exercised (a real provider outage, for example) is demonstrated by fault injection, and that is stated as such.

---

## 7. Unified Evaluation Framework

One framework: **three test suites** (the required evals) scored against **five quality metrics**. Rule-based checks on structured outputs. **Determinism is configured per role, not globally** (§5.1): Job 1 runs at `temperature=0`; Job 2 sets no sampling parameters at all — Claude Sonnet 5 rejects them — so its repeatability rests on the pinned model ID plus structured output, and its response shape is fixed with `output_config.format` rather than assistant prefill, which the model does not support. **Each suite runs 3× in CI and must pass all runs** — this is what makes a 100% threshold enforceable against residual model non-determinism, which for Job 2 is the reason the 3-run rule matters rather than a formality.

### 7.1 Test Suites — 20 cases each, 60 total, 100% pass required

**Suite A — Feasibility (20)**
Shortlist respects budget, bedrooms, and must-haves; commute claims internally consistent with the stated commute point. Mix: tight constraints (5), multiple must-haves (5), boundary values — budget exactly at threshold (5), conflicting preferences (5). **Cases are stratified across at least 3 localities** so the suite is not silently testing one neighborhood. Coverage requirement: **at least one case per filterable field in §3.1's schema**, plus one case asserting that a `null` field is neither counted as a match nor silently dropped. Includes STT-normalization cases ("35k", "thirty-five thousand", locality names) asserted at the constraint-extraction layer.

**Suite B — Edit Correctness (20)**
Voice edits modify only the intended part of the shortlist; untouched listings and their order are byte-identical before/after. Mix: price filters (5), location filters (5), amenity filters (5), compound/sequential edits including a contradiction case (5).

**Suite C — Grounding & Hallucination (20)**
Every shortlisted property maps to a dataset record marked available; every neighborhood claim carries a citation resolving to the correct listing-scoped source; uncertainty explicitly stated where data is missing. Mix: covered neighborhoods (5), partial/no coverage — must declare gaps (5), commute verification against the disclosed method — at least one case per method in §2.3's table (5), safety/amenity claims incl. one injection-content case and **two cross-locality contamination probes — one between adjacent localities (e.g. Koramangala / HSR Layout), one between distant ones** (5). Suite C cases are stratified across at least 3 localities.

**Method disclosure is asserted at three layers per commute case — no extra cases, three assertions on the same run.** The suite stays at 20; what grows is what each commute case checks. A spoken label is worthless if the card beside it is bare, and the card is where a tenant actually reads the number:

| Layer | Assertion | Source of truth |
|---|---|---|
| **Spoken** | The answer contains the mandated method words — `by route` or `straight line` — matching the method actually used | Job 2 output text |
| **Card** | The commute row renders `<value> · <badge>` with the badge matching that same method; `straight-line` rows carry the distinct treatment (§4) | The card view-model |
| **Full label** | The expanded view, snapshot panel and Sources entry resolve to method **+ precomputed-or-live + index date**; a bare `[OSM]` fails | The citation view-model |

- **Assert on the view-model the UI renders from, not on pixels** — these are rule-based CI checks, not screenshot tests; the view-model is what §4's components consume, so asserting there is both deterministic and sufficient
- **All three layers must name the same method.** A case where speech says `by route` and the card badge says `straight-line` fails even though each is individually well-formed — **disagreement between layers is worse than either error alone**, because the tenant has no way to tell which one is lying
- Cases where OSM returned nothing assert the row reads **"not stated"** — not blank, not `0 km` (§3.1, §4)
- A case with no stated commute point asserts the **"Your commute" row is absent**, not empty

### 7.2 Quality Metrics

| Metric | Target | Measured how |
|---|---|---|
| **Latency** | Per §5.2 budget, p99, **scored per turn type** (Type A rows and Type B rows judged separately) | Instrumented across all suite runs + 20 dedicated timed interactions, with per-component timings recorded per §5.2's measurement rules |
| **Accuracy / Precision** | Constraint match >98% · preference extraction >95% · ranking sanity >90% | Rule-based assertions on Suite A structured outputs |
| **Faithfulness / Groundedness** | Factual claims grounded: 100% · citations correct: 100% · fidelity (faithful paraphrase) ≥95% | Manual claim→source verification on Suite C outputs |
| **Hallucination** | **Zero observed hallucinations** across the full grounding suite (~100+ individual claims): 0 fabricated facts, 0 unqualified speculation (opinions require "residents report"/"possibly"-style qualifiers), 0 cross-locality contamination | Claim-level audit of Suite C. *Statistical note: at this sample size, "0 observed" is the honest, testable form of the earlier "<0.5% rate" target — a rate below detection threshold cannot be distinguished from zero, and zero observed is consistent with the 100% pass bar* |
| **Relevance** | Explanation answers the question asked ≥95% · cited source supports its claim ≥98% · shortlist matches preferences ≥95% | Manual review across Suites A & C |

**Automatic-failure red lines:** any fabricated amenity/transit/number; **any distance or travel-time value presented without its method — in speech or on a card — or with a method label that disagrees between the two**; any citation to a source that doesn't contain the claim; **any bare `[OSM]` citation that does not resolve to method + timing**; any cross-locality contamination; any PII surfacing anywhere.

### 7.3 Sign-off

Sign-off requires **every** line below. Any failure → fix → **full** re-run, not a re-run of the failing case.

**Correctness**
- All **60 tests pass on 3 consecutive CI runs** — all three suites, every run
- **Zero red-line events** across those runs (§7.2's list, including the unlabelled-value and layer-disagreement red lines)
- **View-model assertions pass at all three layers** for every commute case (§7.1 Suite C): spoken method words, card badge, and full label — with **all three naming the same method**. A run in which speech and card disagree is a failed run even if each layer is individually well-formed
- Manual spot-check of **10 random outputs per suite**

**Latency (§5.2)**
- Budget met **at p99, scored per turn type** — Type A and Type B judged separately; a Type A pass does not cover Type B
- **No single request exceeded 2× its row's target**
- **Per-component timings recorded** (STT-interim, STT-final, retrieval, LLM first- and last-token, TTS first-byte, each external API call), so any miss is diagnosable without a re-run
- **Cold start measured and reported separately**, outside the budget (§5.2 P1) — reported, not hidden
- **Preconditions P1–P7 verified as actually in force** during the timed runs; a budget met with a precondition silently violated is not met
- Any row that proved unreachable is **renegotiated in §5.2 and re-run** — never quietly dropped

**Artefacts published before sign-off** — each of these is a decision this document deliberately deferred, and sign-off is where they come back:
- The **locality list, per-locality counts, and total** produced by §9.1, written back into §1 and §3.1
- The **bengaluru.rent field-availability gap report** (§3.1), including the availability marker and any schema field the source does not publish
- The **curation rule** used where a locality exceeded 10 listings (§1)
- The **pinned model IDs** for Job 1 and Job 2, with Job 2's **Suite C scores** and its `effort` setting (§5.1)
- The **OSM precompute record**: the fixed query set, and the index date carried by every stored value (§3.4)
- The **§6 walkthrough record** (§6.H): every row exercised or its guard shown, with fault-injected rows labelled as such, and the concurrency actually tested (§6.57)
- The **deployment record** (§5.4): both public URLs, the **Railway region chosen and the measurements that chose it**, confirmation that **app sleeping is off** (or that a keep-warm ping is running, stated as such), and the CORS allowlist actually in force

---

## 8. Out of Scope (MVP)
Login/accounts · post-visit feedback · cross-session preference history · mobile app · languages beyond English · production-grade privacy compliance (demo placeholder PII policy applies regardless).

---

## 9. Implementation Sequence

*A sequence, not a calendar — compress or expand to your own timeline.*

**Ordered by what can invalidate what, not by what is satisfying to build.** Two things in this document can still prove wrong in a way that reshapes the design: **the dataset** (does bengaluru.rent actually carry the fields §3.1 assumes?) and **the latency budget** (§5.2 is derived from the architecture, not measured). Both are settled first, in parallel, behind explicit gates. Everything after them is construction.

---

### Phase 0 — De-risk, in parallel. Nothing downstream is safe until both gates clear.

These two tracks share no dependencies and should run at the same time. Each ends in a **gate**: a written answer, and a decision to proceed or to change the specification.

**9.1 — Data track: scrape, curate, publish**
- Scrape bengaluru.rent; curate to **up to 10 listings per locality**
- **Publish the locality list, per-locality counts, and total.** This number is unknown until now by design (§1) — it is an output, not an assumption
- Identify and document the **availability marker**; document the **curation rule** used wherever a locality exceeded 10
- Produce the **field-availability gap report**: which of §3.1's schema fields the source actually publishes, and which it does not

> **Gate D — Dataset.** If no reliable availability marker exists, or the published schema is materially thinner than §3.1 assumes, **stop and decide before building on it.** A missing field is not a bug to route around later: it changes §3.1's filter vocabulary, §4's cards, and Suite A's coverage requirement. Amend the specification, then proceed.

**9.2 — Infrastructure track: walking skeleton and the latency spike**
- Deploy a **minimal end-to-end skeleton** to Railway and Vercel: health check, the mic WebSocket, one stub turn that touches every provider with placeholder logic
- Run the **latency spike on that deployed skeleton** — real Deepgram, Groq, Anthropic and TTS round trips, **both turn types**, with **P1–P7 actually in force** and per-component timings recorded
- **Compare candidate Railway regions** (a US region against Singapore) and choose on the numbers (§5.4)

> **Gate L — Latency.** Confirm §5.2's table against measurement, or **renegotiate it in writing and update the table**. This must happen on real infrastructure: a local measurement says nothing about the cross-provider, cross-region reality that defines L3 and L5. A missed budget here can change the model choice (§5.1), the region, or the targets themselves — all of which are far cheaper to change now than after the pipeline is built on them.

---

### Phase 1 — Foundations

**9.3 — Knowledge layer**
- Build the **listing-scoped RAG index**: 1–3 documents per locality from the published list, each chunk carrying its source attribution
- **Run the fixed OSM query set once across every listing**, storing each value with its OSM attribution and retrieval date (§3.4). Verify the MCP's routing capability and **lock the commute-method disclosure** wording

**9.4 — Eval harness and the view-model contract** *(before the features they test — deliberately)*
- Build the harness, the fixtures, and **enough of Suite C to validate Job 2**. This has to exist first: §9.7 cannot "validate Job 2 against Suite C" if Suite C is built last
- **Define the card and citation view-model shape now.** Suite C asserts against it (§7.1), so it is a contract between the eval suite, the backend and the UI — not a detail discovered while building §9.9
- Define the **backend contract version** the frontend will pin (§5.4)

---

### Phase 2 — The conversation

**9.5 — Voice pipeline (Job 1)**
- Deepgram with **keyterms generated from the dataset's locality field** and Indian-English amount normalisation; endpointing set explicitly (P3)
- Job 1 structured extraction on Groq at `temperature=0`; streaming TTS starting on the first sentence (P4)
- **Job 1 latency check against Gate L's measured numbers** — if `gpt-oss-120b` misses L1/L2, drop to a lighter Groq tier now (§5.1). Job 1 only has to emit valid JSON

**9.6 — Shortlist and refinement**
- Filtering, ranking and edit application in **application code, not the LLM** — reading the stored dataset and precomputed OSM values
- The `null` rules (§3.1) and the zero-result empty state (§6.1)
- **Suites A and B green**

**9.7 — Grounded explanation (Job 2)**
- Retrieval + Job 2 with citations, gap declarations, and the **commute-method labels at all three layers** (§2.3, §4, §7.1)
- **Suite C green. Pin the model ID and record its Suite C scores and `effort` setting** (§5.1). If a Groq-hosted model matches, collapsing to one vendor is legitimate — decide here, on the scores

---

### Phase 3 — Completing the product

**9.8 — Booking, cancel, reschedule, PDF, email**
- Dual-calendar booking with free/busy slot offers; cancel and reschedule by confirmation code
- **§6.E and §6.F in full** — including the **confirm-time free/busy re-check** (§6.41), **IST-explicit slot arithmetic** (§6.47), and **character-by-character email readback** (§6.50)
- PDF generated on confirmation, emailed, discarded

**9.9 — UI**
- §4's components against the view-models fixed in §9.4, including the commute-method badges
- The failure states §6 requires — in particular, **"couldn't ask" rendered differently from "nothing found"** (principle 2)
- Promote the §9.2 skeleton to the real deployment: **backend to Railway first, frontend to Vercel second**, with the contract version pinned and an explicit CORS allowlist

---

### Phase 4 — Sign-off

**9.10 — Harden, verify, publish**
- Complete all three suites to 20 cases each; run **3× in CI at 100%**
- Full per-component latency instrumentation; **cold start measured and reported separately**
- The **§6 walkthrough** (§6.H): every row exercised or its guard shown, fault-injected rows labelled as such
- Publish the **§7.3 artefact list** and complete sign-off

---

### What invalidates what

If a step in the left column produces a surprise, the right column is what has to change with it. This is the reason for the ordering above.

| Surprise at | Forces revision of |
|---|---|
| **9.1** Dataset thinner than assumed | §1 scope · §3.1 schema · §4 cards · Suite A coverage |
| **9.2** Latency budget unreachable | §5.1 model choice · §5.2 targets · §5.4 region |
| **9.3** Thin or missing neighborhood sources | §3.3 corpus · §6.2 disclaimers · Suite C's coverage mix |
| **9.7** Job 2 misses the grounding bar | §5.1 Job 2 model — and, if nothing reaches the bar, §7.2's target itself, renegotiated openly rather than quietly lowered |

**Parallelism worth taking:** 9.1 and 9.2 run together. So do 9.3 and 9.4 once their gates clear. 9.9's UI work can begin against the §9.4 view-model contract before 9.7 and 9.8 are finished — that contract exists precisely so the two sides can be built independently.

---

**v3.10 is the locked problem statement.**

*Open item carried into execution (not a gap, a deliberate deferral): the locality list and total listing count are produced by §9.1 and must be written back into §1 and §3.1 once the scrape completes.*
