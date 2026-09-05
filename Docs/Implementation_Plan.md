# Voice-based AI Property Scout — Implementation Plan

This is the decision document. It says what gets built, in what order, why that order, what "done" looks like for each piece, and where you will be asked to decide something.

**Companion document:** `Docs/Implementation_Plan_Addendum.md` holds the technical detail for whoever builds each task — every file, function, field, constant, test and command. Each task below ends with a pointer to its addendum section. Builders (human or agent) work from the addendum; you steer from this document.

**Sources of truth:** `Docs/Problem_Statement_Detailed.md` (the specification, v3.10) governs; `Docs/Architecture.md` explains the shape. Where they disagree, the spec wins. "spec §x" and "arch §x" below refer to sections of those two documents.

---

## 1. What we are building, in one paragraph

A voice-first assistant for finding a rental flat in Bengaluru. The tenant speaks their preferences; the assistant reads them back, confirms them, and shows a shortlist of listings; the tenant can ask "why this one?" and get an explanation where every fact names its source; they can then book a visit by voice, receive a confirmation PDF by email, and cancel or reschedule using a 6-character code. Every fact the assistant states carries where it came from, and every failure is shown differently from "nothing found".

## 2. Plain-language glossary (terms used throughout)

| Term | Meaning here |
|---|---|
| **STT / TTS** | Speech-to-text (Deepgram turns the mic into words) / text-to-speech (Smallest.ai turns replies into audio). |
| **Job 1** | The fast language model (Groq, `gpt-oss-120b`) that turns the tenant's sentence into structured edits to their preferences. Never explains anything. |
| **Job 2** | The careful language model (Anthropic, `claude-sonnet-5`) that writes the explanation for "why this one?". Never invents facts; only cites what it is handed. |
| **Type A / Type B turn** | Type A: anything that changes or confirms preferences, or books. Type B: "why?" questions that need Job 2. Decided by simple pattern matching in code, not by a model. |
| **Listing dataset** | Up to 10 listings per locality taken from the supplied spreadsheet `data/Bangalore_Properties_List.xlsx`, cleaned. The sheet carries no owner contact details. |
| **Guide index** | A searchable store of neighbourhood guide chunks (Wikipedia and open city guides), one partition per locality, so answers about HSR Layout can never draw on Koramangala text. Built offline with ChromaDB. |
| **OSM facts** | Distances to the nearest metro, bus stop, etc., computed once at build time from OpenStreetMap through an "MCP" tool server. Never looked up live during a conversation. |
| **Artefact bundle** | The listings + guide index + OSM facts + a manifest (a record of what is in the bundle and how it was built), committed to the repository and loaded when the backend starts. |
| **Provenance** | Every fact is wrapped with its source (dataset / OSM / guide / computed / none), and every distance with its method ("by route" or "straight line"). A fact without a source cannot exist in the code. |
| **Contract** | The fixed shape of everything the backend sends the browser: five kinds of turn result (answered / empty / degraded / failed / needs input), card layouts, messages. Versioned; checked on every connection. |
| **Gate** | A written go / no-go decision that must be recorded before later work starts. There are two: Gate D (dataset) and Gate L (latency). |
| **p99** | The time within which 99 of every 100 requests finish. Latency targets are set on p99, not averages. |
| **Cold start** | The first request after the server process starts; measured and reported separately, never mixed into the budget. |
| **CI** | Automated checks (GitHub Actions) that run the tests on every push. |
| **PII** | Personal information — owner names, phone numbers, emails. Stripped before anything is written to disk. |
| **Eval suites A / B / C** | Three sets of 20 scripted conversations (60 total) that must pass 100 %, three times in a row, before sign-off. A = extraction and matching; B = refinements never reorder untouched results; C = explanations are grounded and commute methods are labelled correctly. |

## 3. Rules that every task obeys

These are the spec's non-negotiables, in plain words. The full list with exact numbers is in the addendum's **Global Constraints** section.

- **Speed.** First feedback under 0.3 s; acknowledgement under 0.7 s with no model involved; first spoken audio within 1.5 s; shortlist on screen under 3 s; explanation text under 6 s; booking confirmed under 5 s; PDF emailed under 30 s. Measured at p99, per turn type; any single request over twice its target is a hard failure. Cold start reported separately.
- **Speed preconditions (P1–P8).** The server never sleeps; connections to every provider are reused; the STT waits 400 ms of silence before ending a sentence, and waits up to another 400 ms if the sentence looks unfinished ("…under" / a bare number); audio starts on the first sentence; OSM facts are precomputed; the two calendar writes run in parallel; Job 2 runs at low effort; a "why?" answer opens with a sentence built by code from facts already known, so audio starts before Job 2 has replied.
- **Models.** Job 1 and Job 2 are different models from different providers, pinned by exact ID. Job 2 is never replaced by Job 1 for explanations. Job 1 may be swapped to a lighter Groq model if it misses the speed targets.
- **Data.** Bengaluru only; up to 10 listings per locality (a ceiling, never padded); duplicates merged when the address matches or coordinates are within 50 m; owner contact is always the placeholder `999999999`. A missing value is shown as "not stated" — never blank, never zero, never guessed — and never satisfies a must-have (such listings go in their own "unknown" group).
- **Grounding.** Listing facts come only from the dataset; distances and amenities only from OSM; neighbourhood character only from the guide index, with a citation; anything else is declared unavailable. Every distance says its method in speech, on the card badge, and in the full label, and the three must agree. Imported listing text and guide chunks are treated as untrusted data, never as instructions.
- **Conversation.** At most 5 clarifying questions per session. Preferences are read back and confirmed before the first shortlist. Contradictions become a question, never a silent change. A refinement changes only what it touches; untouched listings keep their exact order and content. "The second one" means the second one the tenant last heard.
- **Booking.** One Google account, two calendars (Tenant, Owner). Slots: next 7 days, 10:00–18:00 IST, one hour each, first three free ones offered. The 6-character code is the only credential; unknown and cancelled codes get the same answer; lookups are rate-limited. Availability and free/busy are re-checked at the moment of confirming. Cancel/reschedule refused once the slot has started. All time arithmetic in Asia/Kolkata. Email address read back letter by letter before sending. The PDF is generated, emailed, and discarded.
- **Platform.** Backend on Railway (one always-on process); frontend on Vercel (draws what it is given; no server logic). No database, no transcript store, no user table; sessions live in memory and expire. The backend refuses to start if any secret is missing or the bundle does not match its manifest. Logs never contain transcript text or personal data.
- **Out of scope.** Login/accounts, post-visit feedback, cross-session history, mobile, languages other than English, production-grade privacy compliance.

## 4. The order of work, and why

The order follows the spec's §9: **do first whatever could invalidate everything after it.**

| Phase | Settles | Ends with |
|---|---|---|
| **0 — De-risk** | Can we get the data at all? Can real infrastructure meet the speed targets? | **Gate D** and **Gate L**, both decided in writing |
| **1 — Foundations** | The knowledge layer (guides, index, OSM facts), the bundle loader, the contract, the test harness | A complete bundle, a backend that boots on it, 5 Suite C cases written *before* Job 2 exists |
| **2 — Conversation** | The voice pipeline, Job 1, the shortlist engine, Type A turns, retrieval, Job 2, Type B turns | All 60 eval cases green three times; Job 2 scores recorded |
| **3 — Product** | Booking, cancel, reschedule, PDF + email, the real UI, promotion to production | A stranger with the URL can do the whole journey |
| **4 — Sign-off** | Latency measured on production, every failure row exercised, three green CI runs | The spec §7.3 checklist, every line ticked with evidence |

**Work that can run in parallel:** the data track (0.4–0.6) alongside the infrastructure track (0.7–0.10); the knowledge layer (1.1–1.3) alongside the store/contract/harness (1.4–1.6) once both gates clear; the UI (3.5–3.6) can start against the contract from Task 1.5 before Phase 2 finishes.

**Working conventions (short form):** one commit per task; tests are written before the code they test; provider SDK signatures are checked against the installed library before use (the plan's provider shapes are from vendor docs dated 2026-08-30 and can drift); secrets live only in `backend/.env` locally and Railway variables in production; raw guide fetches are never committed. Full conventions and the repository file tree: addendum → *Conventions* and *File structure*.

## 5. Decisions you will be asked to make

| When | Decision | What you will have in hand | If it goes the wrong way |
|---|---|---|---|
| Task 0.1 | Only if Python 3.12 is not installed: install it, or prove the libraries work on 3.14. | The result of `pip install chromadb onnxruntime` on 3.14. | Build breaks on missing wheels later. |
| Task 0.4 | **Settled.** The listing source is the supplied spreadsheet `data/Bangalore_Properties_List.xlsx`; bengaluru.rent is out of scope and is never fetched. No crawling decision remains. | The field inventory, recorded in `data/SOURCE_NOTES.md`. | — |
| Task 0.6 — **Gate D** | One of: **Proceed** (availability marker exists, every schema field is published) · **Proceed with spec amendment** (list the missing fields; amend spec §3.1/§4/§7.1 in the same commit) · **Stop** (no reliable availability marker). | Locality list and counts, the availability marker (or "none found"), the fields the sheet does not carry, whether floor area is carpet or built-up, and the import's cost in rows and minutes. | Building on a dataset that cannot say whether a listing is still available. |
| Task 0.10 — **Gate L** | One of: **Proceed** (every speed row met at p99, no 2× violation; choose the region and say why) · **Proceed with renegotiation** (name the rows that missed; update spec §5.2 and this plan's rules in one commit) · **Change the model** (Job 1 missed; switch to a lighter Groq model and re-run). | A table of p99 timings per stage for two Railway regions (US and Singapore), cold-start numbers, the false end-of-speech rate on Indian-English speech, and which preconditions were actually in force. | A speed budget that is quietly ignored — the failure mode the spec names. |
| Task 1.1 | Which 1–3 guide pages to use per locality (Wikipedia plus up to two open city guides; no listing portals or advertising copy). Localities with no usable source are recorded as empty — Suite C must then prove the assistant says so. | The locality list from Gate D. | Contaminated or thin neighbourhood answers. |
| Task 1.3 | Accept the commute wording as locked, and note whether routing worked for ≥ 90 % of listings. If not, most transit claims will say "in a straight line" and the demo should expect that. | The routed / straight-line / null split printed by the precompute. | A demo that surprises you. |
| Task 2.4 | If Job 1 refuses strict JSON mode or misses the intent on a plain sentence: try the lighter Groq tier now, and note it in Gate L's model row. | Three live utterances against the real Groq client. | Late discovery that Job 1 cannot hold the role. |
| Task 2.13 | **Pin Job 2.** Keep `claude-sonnet-5` at low effort unless a Groq-hosted alternative also scores 20/20 three times on Suite C. Also: whether the "hybrid retrieval" upgrade is triggered (only if exact-name questions fail because dense search blurred them). | `Docs/JOB2_SCORES.md`: pass counts for three runs, dropped-sentence counts, the L3/L5 timings. | Either a slower/costlier explanation model than needed, or one that hallucinates. |
| Task 3.2 | Operator setup in Google Cloud: enable Calendar + Gmail APIs, create an OAuth desktop client, create the two calendars in the demo account. | Nothing to decide technically; it is your account. | Booking cannot be built or tested. |
| Task 4.1 | If any production latency row misses: renegotiate spec §5.2 and this plan's rules in one commit, then re-run. | `Docs/LATENCY_REPORT.md`. | Sign-off on numbers that were not met. |
| Task 4.3 | Sign off. | Three green CI runs of 60/60, the manual spot-check, the published artefacts list. | — |

**What this plan does not tell you:** it carries no estimates of build time or running cost (provider bills, Railway, Vercel). Gate D records the import's cost; Gate L and the latency report record timings; nothing else is costed. If you want a cost view, that is a separate piece of work.

---

## Phase 0 — De-risk

Nothing after this phase is safe until both gates clear. Tasks 0.1–0.3 are shared groundwork; 0.4–0.6 are the data track; 0.7–0.10 the infrastructure track. Run the two tracks in parallel.

### Task 0.1 — Repository scaffold, toolchain, CI skeleton
- **Delivers:** a Python backend project (pinned to Python 3.12, every dependency pinned to an exact version), a Next.js frontend project, an example environment file listing every secret's name, a CI workflow that runs the tests, and the ignore rules that commit the bundle but never raw guide fetches.
- **Why now:** everything else needs somewhere to live and a green test run to start from.
- **Done when:** backend unit tests pass, the frontend builds, CI is green on the scaffold.
- **Decision:** see §5 (Python 3.12 vs 3.14).
- Detail: addendum → Task 0.1.

### Task 0.2 — The fact wrapper and the one commute formatter
- **Delivers:** the small type that wraps every fact with its source and, for distances, its method — the code refuses to create a distance without one. Plus the single function that turns a distance into (a) the spoken words, (b) the card badge, (c) the full label, so the three can never disagree. "Not stated" is defined here, once.
- **Why now:** these two pieces are what make the grounding rules enforceable rather than aspirational; everything downstream is built on them.
- **Done when:** 12 unit tests pass.
- Detail: addendum → Task 0.2.

### Task 0.3 — Domain records: listing, OSM fact, guide chunk, manifest
- **Delivers:** the data shapes — the listing record with exactly the spec's fields (each may be null), the fixed set of OSM queries to run for every listing, the guide-chunk record, and the manifest that records what the bundle contains and how it was built (versions, counts, curation rule, missing fields, embedding model fingerprint).
- **Why now:** the importer (0.5), the index (1.2) and the OSM precompute (1.3) all write these shapes.
- **Done when:** the domain suite passes — 29 tests as of 2026-09-05.
- Detail: addendum → Task 0.3.

### Data track — Tasks 0.4 to 0.6 → Gate D

### Task 0.4 — Source inventory: what the supplied spreadsheet publishes
- **Delivers:** evidence, not code. A notes file recording which schema field maps to which sheet column, which fields the sheet does not carry, whether an availability marker exists, whether floor area is carpet or built-up, and how each column was produced.
- **Why now:** the importer (0.5) and the gap report (0.6) both read this inventory; nothing downstream can assume a field the sheet lacks.
- **Done when:** the notes file is complete in its fixed skeleton (so Task 0.6 can read it mechanically) and committed.
- **Status: done** (rewritten 2026-09-05 for the re-supplied sheet). `data/SOURCE_NOTES.md` records 16 of 24 schema fields present, an availability marker (`availability_status`, 4,532 `Yes` / 4,648 `No`), three PII columns that are never imported (`Name`, `Phone Number`, `Voter ID`), and `area_basis` unknown. It also records that rent, deposit and the other descriptive columns are **randomly generated placeholders**, not observed market data.
- Detail: addendum → Task 0.4.

### Task 0.5 — Importer: read the spreadsheet, dedupe, write records
- **Delivers:** the importer that reads `data/Bangalore_Properties_List.xlsx` into `ListingRecord[]`, maps each column to its schema field, merges duplicates (within 50 m and otherwise identical; the more detailed record wins), and writes all parsed records (no cap yet). Fields the sheet does not carry stay null. The three PII columns the sheet gained on 2026-09-05 are never read: the importer works from a column allow-list, and the PII guard sits behind it as defence in depth.
- **Why now:** the dataset is the first thing that can invalidate the project.
- **Done when:** unit tests pass on a small fixture sheet, one full import has run, and a search of the output finds no 10-digit numbers and no `@`.
- **Status: done.** 9,180 records over 566 localities imported to `data/raw/listings_all.json`; no name, phone number or voter ID from the sheet reaches the output.
- Detail: addendum → Task 0.5.

### Task 0.6 — Curate to ≤ 10 per locality, gap report, manifest → **Gate D**
- **Delivers:** the curation step (records marked unavailable are dropped and a null marker is kept, as spec §3.1 requires; per locality keep the 10 most detailed; ties broken by as-of date then id; the rule is written down as a sentence), a report of which fields are actually published, the first half of the manifest, and the committed listings file.
- **Why now:** this is the moment to decide whether the dataset can carry the product.
- **Done when:** `data/GATE_D.md` has exactly one box ticked; if the spec had to be amended, it is amended in the same commit, and the locality list and total are written back into spec §1 and §3.1.
- **Decision:** **Gate D** — see §5.
- **Status: done.** Gate D re-decided 2026-09-05 (first decided 2026-09-02): **proceed with spec amendment**. 2,370 listings over 464 localities — 128 at the 10 ceiling, 336 below it; availability marker `availability_status` present, so the 4,648 rows marked unavailable are dropped and 102 localities fall out entirely; seven fields never published and `area_basis` unknown throughout (`data/GATE_D.md`).
- Detail: addendum → Task 0.6.

### Infrastructure track — Tasks 0.7 to 0.10 → Gate L

### Task 0.7 — Settings, boot checks, telemetry, `/health` and `/contract`
- **Delivers:** typed settings read from the environment (every secret, the model IDs, the 400 ms / 400 ms / 1 s speech-timing values); the boot-check framework that runs every check, collects *all* failures, and stops the process before it opens its port; per-turn tracing with the span names the spec's measurement rules require (and a file export for the latency spike); the two tiny HTTP endpoints; the app factory.
- **Why now:** the skeleton deployed in 0.9 must already fail loudly on a missing secret, and Gate L needs the timing spans.
- **Done when:** unit tests pass; a missing secret makes the process exit non-zero.
- Detail: addendum → Task 0.7.

### Task 0.8 — Walking skeleton: the mic WebSocket and one stub turn touching every provider
- **Delivers:** the real WebSocket gateway (first message must carry the contract version or the socket is closed), the real wrappers for Deepgram, Groq, Anthropic and Smallest.ai, and a placeholder turn that exercises each of them end to end — including the "opener before Job 2 replies" trick on the Type B leg. Each provider SDK's actual call signature is checked and written into a comment before use.
- **Why now:** Gate L is measured on this skeleton. The gateway and wrappers written here are kept; only the stub turn is replaced later (Task 2.10).
- **Done when:** the handshake tests pass; with real keys, the three provider ping tests pass.
- Detail: addendum → Task 0.8.

### Task 0.9 — Deploy the skeleton: Railway (backend) then Vercel (frontend), with a bare mic page
- **Delivers:** the Dockerfile and Railway config; a public backend URL answering `/health`; the browser-side microphone capture (16 kHz mono, 20 ms frames), audio player, and WebSocket client; a bare page with one mic button; the CORS allowlist containing exactly the production frontend origin plus localhost. Two Railway services (US and Singapore) if you want to compare regions — Gate L needs both numbers.
- **Why now:** the speed targets can only be judged on real infrastructure, from a real browser.
- **Done when:** in the browser you can click the mic, speak, see words appear while speaking, hear "You said …" back; and blanking a key makes the deploy fail its health check.
- Detail: addendum → Task 0.9.

### Task 0.10 — Latency spike on real infrastructure → **Gate L**
- **Delivers:** a script that replays two recorded utterances (ideally an Indian-English speaker) against the deployed skeleton 25 times per turn type per region and times every stage; a scorer that computes p99 per stage and flags any request over twice its target; a deliberate cold-start measurement; the false end-of-speech count (how often "…under forty thousand" got cut at the pause, out of 20 tries); and the written gate decision.
- **Why now:** if the targets cannot be met on this infrastructure with these models, the spec must change before anything is built on it.
- **Done when:** `data/GATE_L.md` has exactly one box ticked, with the numbers, the region chosen, and — if renegotiated — the spec and this plan's rules changed in the same commit. The unused Railway region service is deleted.
- **Decision:** **Gate L** — see §5.
- Detail: addendum → Task 0.10.

**Phase 0 exit:** both gate files have exactly one box ticked, and any spec amendment they required is committed.

---

## Phase 1 — Foundations

Both gates have cleared. 1.1–1.3 (the knowledge layer) and 1.4–1.6 (store, contract, harness) can run in parallel.

### Task 1.1 — Collect guide documents and chunk them semantically
- **Delivers:** a hand-written list of 1–3 guide URLs per locality; a collector that fetches them politely (1 s between requests) and keeps only readable paragraphs; a chunker that splits on paragraph boundaries and merges neighbours while they stay on the same topic (60–220 words, never cutting mid-sentence); the embedding model pinned by name and by a fingerprint of the downloaded weights file.
- **Why now:** the guide index needs its material, and the embedding model must be pinned before anything is indexed.
- **Done when:** chunker tests pass; five random chunks each read as a passage that could stand as a citation on its own.
- **Decision:** see §5 (choice of sources).
- Detail: addendum → Task 1.1.

### Task 1.2 — Build the guide index: one collection per locality
- **Delivers:** the index build (one ChromaDB collection per locality, rebuilt from scratch each time), and the manifest gaining the embedding model, its fingerprint, chunk counts per locality, the guide sources, and the library versions.
- **Why now:** partitioning by locality is what makes cross-locality contamination impossible by construction.
- **Done when:** tests pass; a smoke query "is it noisy at night?" against Koramangala returns passages about nightlife/noise in Koramangala, not another locality.
- Detail: addendum → Task 1.2.

### Task 1.3 — Precompute OpenStreetMap facts for every listing
- **Delivers:** a wrapper around the OSM MCP server (its real argument names read from the server's own schema before use); for every listing × every query in the fixed set, one row — routed distance and duration when routing works, straight-line when it does not, an all-null row when nothing is found (the row still exists). The manifest gains the query set and the retrieval date.
- **Why now:** no OSM lookup is allowed during a conversation, so all of it must exist before Phase 2.
- **Done when:** the facts file has exactly listings × queries rows; the routed / straight-line / null split is printed and the ≥ 90 % routing note is recorded in Gate L's footer.
- **Decision:** see §5 (commute wording locked; routing coverage expectation).
- Detail: addendum → Task 1.3.

### Task 1.4 — Artefact store and the boot checks
- **Delivers:** the read-only loader for the whole bundle, and the boot checks that refuse to start the server unless: the bundle loads, its version matches the contract version, every listing × query has an OSM row, and the loaded embedding model's fingerprint equals the manifest's. Plus a tiny 2-locality, 3-listing test bundle (with a deliberately contaminating chunk so the later contamination test has teeth).
- **Why now:** from here on, every test and every deploy runs against a bundle that is known to be internally consistent.
- **Done when:** unit tests pass and the backend boots locally against the real bundle.
- Detail: addendum → Task 1.4.

### Task 1.5 — The contract: turn outcomes, view-models, messages, schema export
- **Delivers:** the five distinct turn-result shapes (answered / empty / degraded / failed / needs-input — "nothing found" and "couldn't ask" can never look alike), the card and panel layouts (every missing value already rendered as "not stated"), the WebSocket and HTTP message shapes, and a JSON Schema export from which the frontend generates its types. A CI job fails if the exported schema drifts from the committed one.
- **Why now:** the eval suites assert on it, the UI is generated from it, and the backend must never change it silently.
- **Done when:** contract tests pass; the schema file is committed; the drift job is green.
- Detail: addendum → Task 1.5.

### Task 1.6 — Eval harness: driver, fixtures, assertions, suite skeletons, first Suite C cases
- **Delivers:** a driver that feeds typed text turns straight to the conversation engine (no audio); a frozen slice of the real bundle (3 localities — two adjacent, one distant — ≤ 5 listings each); the three reusable assertions (three-layer commute agreement; untouched listings byte-identical; every claim cites something in the right locality); the three suite files; the first 5 Suite C cases including the injection probe and the adjacent-locality contamination probe; the CI job that runs the evals three times.
- **Why now:** the spec requires Suite C to exist before Job 2 is written, so the model is measured against a test it did not shape.
- **Done when:** the suites are collected and marked "expected to fail until Task 2.10"; the fixture slice is committed.
- Detail: addendum → Task 1.6.

**Phase 1 exit:** the bundle is complete (listings, OSM facts, chunks, index, manifest with every field); the backend boots on it locally; the contract schema is checked in with a green drift job; 5 Suite C cases exist.

---

## Phase 2 — The conversation

### Task 2.1 — Constraints, session manager, and the turn state machine
- **Delivers:** the immutable preference set (localities, BHK, rent range, deposit cap, furnishing, property type, parking, lift, amenities, minimum size, move-in date, commute point, and which of these have been confirmed); the shortlist shape (matched / unknown / excluded); the in-memory session (with its lock, its pending action, its count of clarifying questions asked, and what the tenant last heard); sessions expire on a timer; a second browser tab is a second session. The turn state machine with exactly the architecture's allowed transitions, including barge-in.
- **Why now:** every later task reads or writes these.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.1.

### Task 2.2 — Content-aware hold and the Type A / Type B router
- **Delivers:** the rule that says an interim transcript "looks unfinished" (ends in under / above / near / with / and / about / around / to / below / over / between / or, or a bare number) so the gateway waits up to 400 ms more; and the router that sends a turn to Type B only when it matches an explanation pattern *and* there is a shortlist to explain.
- **Why now:** the router is pattern matching in code — a deliberate decision that no model call sits in front of Job 1.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.2.

### Task 2.3 — Deepgram keyterms from the dataset, and Indian-English amount normalisation
- **Delivers:** the list of words the STT should favour, generated from the manifest's locality names plus a fixed handful (BHK, lakh, deposit, …) — never hand-typed; and the amount parser that understands "35k", "35,000", "thirty five thousand", "1.2 lakh", "one point two lakh", and treats a bare "thirty five" as ambiguous (35 / 35,000 / 3,50,000) so the assistant asks rather than guesses.
- **Why now:** Suite A asserts on normalised amounts; the STT must know the locality names before Gate-L-grade speech tests mean anything.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.3.

### Task 2.4 — Job 1: extraction and edit routing on Groq
- **Delivers:** the strict output schema for Job 1 (intent, a list of one-field edits, ambiguities with the question to ask, a reference like "the second one", email, code, slot choice); the system prompt; retry once on a schema violation, then treat Job 1 as down; amounts normalised here; a locality outside the dataset becomes a question ("not covered; nearest covered is …"), never a silent substitution.
- **Why now:** it is the first real model call in the pipeline.
- **Done when:** unit tests pass with a faked Groq; three live utterances pass against the real client.
- **Decision:** see §5 (lighter Groq tier if strict mode fails).
- Detail: addendum → Task 2.4.

### Task 2.5 — The constraint reducer: one field at a time, contradictions become questions
- **Delivers:** a pure function that applies one edit to the preference set, changing exactly one field and marking it unconfirmed; the contradiction rules (max below min, min above max, non-positive deposit or size, a move-in date in the past) each yielding a question; edits stop at the first contradiction.
- **Why now:** this is where "contradictory edits ask, never silently break" is made true.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.5.

### Task 2.6 — Shortlist engine and the availability overlay
- **Delivers:** the matcher (hard fields evaluated in a fixed order; a null on a required field is *unknown*, never a match, never dropped); the ranking (most soft matches first, then rent ascending with unknown rent last, then id); refinement that keeps still-matching listings in their previous relative order and appends newcomers after; the empty-state helpers that name which field excluded the most listings and suggest relaxations (suggest only — nothing is relaxed automatically); and the in-memory availability overlay an operator can flip, which dies with the process.
- **Why now:** the shortlist is plain code by design — no model decides what is shown.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.6.

### Task 2.7 — Commute service: precomputed OSM reads and live straight-line arithmetic
- **Delivers:** reads of the precomputed transit facts (with source, method, date, citation reference), and the straight-line distance from a listing to the tenant's stated commute point computed live with no network. Commute points are resolved from a small build-time table of named Bengaluru places (locality centroids plus a few work hubs such as Whitefield, Electronic City, Manyata Tech Park, MG Road); an unknown place makes the assistant ask "Where do you commute to? I know …".
- **Why now:** Type A results already show transit; Suite C's commute assertions depend on this.
- **Done when:** unit tests pass; the places table is in the bundle.
- Detail: addendum → Task 2.7.

### Task 2.8 — View-model builder: cards, locality groups, "not stated", badges, sources
- **Delivers:** the code that turns listings and shortlists into what the browser draws — rupee formatting with Indian grouping, "not stated" for every null, the size label with its carpet/built-up basis, the transit row with its method badge, the tenant-commute row only when a commute point exists, cards grouped by locality in ranked order, and citation labels (dataset / OSM / guide) so a bare "[OSM]" can never appear.
- **Why now:** the frontend must be "dumb" — it draws finished view-models and computes nothing.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.8.

### Task 2.9 — Speaking: sentence splitting and streaming TTS that starts on the first sentence
- **Delivers:** a sentence splitter that never breaks after "₹35,000." decimals, "Rs.", "sq." or a lone number; and the speaker that streams audio sentence by sentence, supports barge-in (stop and tell the browser), and treats a TTS failure as "finish the turn in text" rather than an error.
- **Why now:** precondition P4 (audio starts on the first sentence) lives here.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.9.

### Task 2.10 — The turn orchestrator (Type A), the live session, and Suites A + B green
- **Delivers:** the one component that knows the whole turn: Job 1 → out-of-scope and owner-contact replies → booking hand-off → "the second one" resolution (with a check that the list has not changed since it was heard) → clarifying questions within the 5-question budget (then proceed provisionally and say so) → readback and confirmation before the first shortlist → refinement afterwards → the empty state that names the binding constraint. Speech starts as a background task so the result returns without waiting for audio. Also the WebSocket-side live session (STT stream, interim transcripts, the 400 ms hold, acknowledgement before any model, a 30 s runaway cap, barge-in, keepalive, one STT reconnect, typed-text fallback). The stub turn from 0.8 is deleted. The 20 Suite A and 20 Suite B cases are written (their content is tabulated in the addendum).
- **Why now:** this is the first complete Type A conversation.
- **Done when:** unit tests pass; Suites A and B pass 40/40, three times in a row. A flaky case is a Job 1 prompt problem or a case-wording problem — assertions are never loosened.
- Detail: addendum → Task 2.10.

### Task 2.11 — Retrieval (partitioned) and the resolver registry
- **Delivers:** retrieval that queries only the asked locality's collection; and the registry through which Job 2 reaches facts — the dataset resolver (rent, deposit, maintenance, BHK, furnishing, parking, lift, floor, size, move-in date, society), the OSM resolver (every precomputed query), the document resolver (that locality's chunks), and an "unavailable" resolver for anything else. Job 2 receives nothing except the resulting fact bundle.
- **Why now:** the grounding boundary is a call graph, not a prompt instruction; this task builds the graph.
- **Done when:** unit tests pass.
- Detail: addendum → Task 2.11.

### Task 2.12 — Job 2: grounded explanation with streaming sentences, and the claim assembler
- **Delivers:** Job 2's strict output (sentences, each with the fact references it relies on, plus declared gaps); a stream parser that releases each sentence as soon as it is complete; a prompt that lists facts as "reference: value (source, method, date)" and wraps guide chunks in untrusted-document delimiters; and the assembler that drops any sentence citing a reference not in the bundle, citing nothing, or asserting a value where every cited fact is a gap. Gap lines are humanised ("I don't have a deposit figure for this listing").
- **Why now:** this is the only place a model writes prose the tenant hears, so it is fenced on both sides.
- **Done when:** unit tests pass; a live check against the real client binds at least one sentence and cites nothing outside the bundle.
- Detail: addendum → Task 2.12.

### Task 2.13 — The fact-led opener, lane B, Suite C to 20 — pin Job 2
- **Delivers:** the opener built by code only from resolved facts (rent, BHK, transit with method words, commute with method words and caveat) — spoken immediately, before Job 2 replies; lane B in the orchestrator (resolve → opener → stream Job 2 → bind each sentence → speak it as it binds → explanation and snapshot panels); Job 2 down yields a *degraded* result (shortlist and opener stay; explanation withheld and named as missing) — never a Job 1 substitute; Suite C extended to 20 cases (covered neighbourhoods, partial/no coverage, five commute cases covering both methods and the null row, safety/amenity, the injection probe, adjacent and distant contamination probes); `Docs/JOB2_SCORES.md`.
- **Why now:** Job 2 must earn its role on the suite before it is pinned.
- **Done when:** Suite C passes 20/20 three times; the scores document exists; the model decision is recorded.
- **Decision:** see §5 (pin Job 2; hybrid retrieval trigger).
- Detail: addendum → Task 2.13.

**Phase 2 exit:** all 60 cases pass locally three times; the deployed backend serves a full Type A and Type B conversation (the frontend still shows raw results until Phase 3).

---

## Phase 3 — Completing the product

### Task 3.1 — Booking domain types and the IST slot service
- **Delivers:** the slot and booking records; the slot service (next 7 days from the next full hour, 10:00–18:00 IST, one-hour slots not overlapping busy time, first three offered, "has this slot started?", parse a requested time); every function takes "now" explicitly and converts it to Asia/Kolkata. A lint rule that flags any clock read without a timezone anywhere in the codebase.
- **Why now:** all booking logic sits on these, and the timezone rule is easiest to enforce before the code exists.
- **Done when:** unit tests pass and the timezone lint is clean.
- Detail: addendum → Task 3.1.

### Task 3.2 — Google Calendar and Gmail adapters, and the one-time OAuth script
- **Delivers:** the one-time script that authorises the demo Google account (Calendar + send-mail scopes) and prints the credentials to paste into the environment; the calendar adapter (free/busy, insert with the code stored on the event, delete that treats "already gone" as success, find-by-code across both calendars); the Gmail adapter (send with a PDF attached); auth failures surfaced as an operator problem.
- **Why now:** the booking service (3.3) is built on faked versions of these, then verified live.
- **Done when:** unit tests pass; with credentials, one event is inserted, found by code, and deleted on the Owner calendar.
- **Decision:** see §5 (Google Cloud setup).
- Detail: addendum → Task 3.2.

### Task 3.3 — Booking service and HTTP routes
- **Delivers:** the 6-character code generator (letters and digits that cannot be confused: no 0/O/1/I); offer (owner free/busy, first three); confirm (re-check availability, then free/busy, then both calendar writes in parallel; if one half fails it is queued for retry and the booking is still confirmed; if both fail the booking still stands and the tenant is told the calendar is unreachable); lookup (unknown and cancelled both answer "not found"); cancel; reschedule (same code kept; same slot answers "unchanged"); the retry queue; the HTTP routes with code endpoints rate-limited to 10 per minute per client; the operator-only availability toggle.
- **Why now:** the booking rules in §3 are made true here, once, for both voice and HTTP.
- **Done when:** unit tests pass, including: unknown and cancelled codes get exactly the same 404; the 11th call in a minute gets 429; the operator route without its token gets 401.
- Detail: addendum → Task 3.3.

### Task 3.4 — PDF + email, and booking by voice
- **Delivers:** the confirmation PDF (listing, locality, visit time in IST, the code, owner contact `999999999` labelled "demo placeholder — not a real number") generated in memory, emailed, then discarded; resend limited to 3 per code per hour; and the voice booking flow — book → three slots → choice ("the second one") → email, read back letter by letter → confirm → code spoken with spaces; listing withdrawn mid-flow → removed from the shortlist and the rest re-read; cancel and reschedule by voice with the same code.
- **Why now:** replaces the "booking isn't available in this build yet" placeholder from Task 2.10.
- **Done when:** unit tests pass; a real booking by voice through the deployed backend puts entries on both calendars, the email arrives with the PDF, and cancelling by code removes both.
- Detail: addendum → Task 3.4.

### Task 3.5 — Frontend: transport and audio hardening
- **Delivers:** reconnect with backoff (1 s, 2 s, 4 s, then "can't reach the service"); a contract-version mismatch that names itself; microphone denied / no device / device lost handled with recovery text; pause capture when the tab is hidden; the HTTP client; and the browser's state store with tested rules — a failed turn never clears the previous shortlist, and "unreachable" is its own state, never an empty shortlist.
- **Why now:** can start against the Task 1.5 contract before Phase 2 finishes.
- **Done when:** the reducer tests pass and the frontend builds.
- Detail: addendum → Task 3.5.

### Task 3.6 — Frontend: components and failure states
- **Delivers:** the shortlist cards (locality as the heading; deposit and maintenance always shown; "not stated" everywhere a value is missing; size labelled "sq ft", never "area"; the method badge never dropped for width, with straight-line visibly distinct from by-route), the snapshot and sources panels (every citation labelled, linked where a URL exists), mic control with states and the "Enable voice" fallback, transcript line, question prompt, booking panel and code entry, the empty state ("I won't relax anything myself"), and the failure banner — styled and worded differently from the empty state, with a Retry button when retrying is worth it. Reload mid-conversation shows "Your conversation was not saved; a confirmed booking still works with its code".
- **Why now:** the last piece of the visible product.
- **Done when:** component tests pass, the frontend builds, and one full conversation, one explanation, one booking and one cancel-by-code work locally.
- Detail: addendum → Task 3.6.

### Task 3.7 — Promote to the real deployment: backend first, then frontend
- **Delivers:** backend on Railway with the full bundle (boot checks visible in the log; app sleeping off; the region Gate L chose); then the frontend on Vercel; CORS allowlist exactly the production origin (preview deployments are not added; verified with a request from a foreign origin); `Docs/DEPLOYMENT_RECORD.md` with URLs, region and the numbers that chose it, the allowlist, the contract and bundle versions.
- **Why now:** backend first so the frontend never speaks to a version that does not exist.
- **Done when:** the deployment record is written.
- Detail: addendum → Task 3.7.

**Phase 3 exit:** a stranger with the URL can speak a requirement, hear and read a shortlist, ask why, book a visit, receive a PDF, and cancel with the code — on the production URLs.

---

## Phase 4 — Sign-off

### Task 4.1 — Full latency instrumentation, the 20 timed interactions, cold start
- **Delivers:** 20 scripted interactions against production (8 Type A, 6 Type B, 3 bookings, 2 cancel/reschedule, 1 PDF timed to inbox arrival); a checker that proves each precondition P1–P8 was actually in force from the traces and the Railway settings; a deliberate cold-start measurement reported separately; two interactions run at once to report the concurrency tested; and `Docs/LATENCY_REPORT.md` with the p99 table per turn type, the 2× check, and per-component timings.
- **Done when:** the report is written; any missed row is renegotiated in the spec and this plan in one commit and re-run.
- **Decision:** see §5.
- Detail: addendum → Task 4.1.

### Task 4.2 — The §6 walkthrough: every failure row exercised or its guard shown
- **Delivers:** an operator-gated fault switch (off by default; proven absent by a test) that can make any provider fail on demand; and `Docs/ERROR_WALKTHROUGH.md` with one line per spec §6 row (58 rows) — how it was exercised (real, fault-injected, or the guard shown in code), what was observed, and whether it matches. Rows needing a real outage are fault-injected and labelled so; the browser rows are exercised by hand in Chrome, Firefox and Safari.
- **Done when:** every row has a line.
- Detail: addendum → Task 4.2.

### Task 4.3 — Three green CI runs, the published artefacts, sign-off
- **Delivers:** three consecutive CI runs at 60/60 (any failure means fixing and re-running all three, never re-running one case); a human spot-check of 10 outputs per suite against the source; `Docs/SIGNOFF.md` with the spec §7.3 checklist — correctness, latency, and the published artefacts (locality list and counts written back into the spec, gap report and availability marker, curation rule, pinned model IDs and Suite C scores, OSM precompute record, build manifest, the §6 walkthrough, the deployment record); the README status line; a `v1.0-signoff` tag.
- **Decision:** sign-off — see §5.
- Detail: addendum → Task 4.3.

---

## 6. Things this plan cannot settle yet

- **The site's page structure and its availability marker** — found by looking (Task 0.4); Gate D may amend the spec.
- **The OSM tool server's exact argument names** — read from the server itself before use (Task 1.3).
- **Provider SDK call signatures** — checked against the installed libraries before the first call (Tasks 0.8, 2.3, 2.12); the plan's shapes are from vendor docs dated 2026-08-30.
- **Whether Job 1 (`gpt-oss-120b`) holds the speed targets** (Gate L) and **whether Job 2 (`claude-sonnet-5` at low effort) holds Suite C** (Task 2.13) — both are measured, both have a named fallback.
- **The Python interpreter** — 3.12 assumed for library availability; the machine has 3.14.5.

## 7. Where each spec requirement lands

The addendum's final section, **Spec coverage map**, lists every spec and architecture requirement against the task(s) that satisfy it, so a gap is visible before work starts rather than at sign-off.

## 8. Voice agent persona — the prompt list

The persona is specified in **arch §11.2**. This is the builder's copy: the seven blocks below are the prompt text, followed by where each one actually lands in the code. Nothing here loosens a rule in §3 — the persona sets the *voice*, never what may be claimed.

**P-1 · Role**
> You are a professional property service agent with deep experience in understanding what a buyer or renter needs, and in giving them useful information for scouting a property that matches their preferences.

**P-2 · Identity**
> Your name is Nakshatra and you are female. You are sweet in manner and have impressive knowledge of real estate and properties in Bengaluru. You have a welcoming, likeable attitude, and you are polite, respectful and empathetic.

**P-3 · Goal**
> Help the renter book a slot for a property visit: block the calendars, give them their visit code, and send the confirmation email with the PDF, exactly as this project defines those steps.

**P-4 · Speech style**
> Keep each response under 3 sentences. Speak naturally and calmly. Use short pauses and avoid monologues. Use simple, everyday language and avoid jargon.

**P-5 · Capabilities**
> Acknowledge and appreciate the renter's preferences. Keep building their preferences with them and move towards booking a slot. Do not deviate from this project's subject. Do not invent anything — every answer must be grounded in the facts you are handed. Take feedback and let it improve your next response. Keep the conversation engaging and meaningful.

**P-6 · Privacy**
> Never ask about personal information or financial details. Rent, deposit and budget are the only money topics. The one exception is the renter's email address, asked only at the confirmation step because the PDF cannot be sent without it; read it back letter by letter and never ask for a name, phone number, ID, employer, income or bank detail.

**P-7 · Opening**
> When the renter clicks the microphone, greet them first. Introduce yourself, your role and what you can do, in no more than 3 sentences or 150 words, and then ask for their preferences with one or two examples.

### Where each block lands

| Block | Lands in | Task |
|---|---|---|
| **P-7** | A fixed greeting template spoken on the mic click — **code, not a model call**, so it costs nothing from the latency budget and cannot invent a claim | 2.9 (speaker) + 3.6 (mic control) |
| **P-4, P-5** | The wording of the code-built conversational replies: readback, clarifying questions, empty state, booking prompts | 2.10 |
| **P-1, P-2, P-3** | Tone and framing in Job 2's system prompt; Job 1 never speaks, so it carries none of this | 2.12 |
| **P-6** | Enforced in code, not by wording: the only personal field the flow ever collects is the email at confirm time, read back letter by letter, held in the session and discarded | 3.4 |

**Three cautions for whoever builds this.**

1. **The persona never overrides the assembler.** A Job 2 sentence that is warm, on-brand and uncitable is still dropped (arch §9.4). If the tone makes Job 2 pad sentences that then get dropped, shorten the tone instruction — do not loosen the assembler.
2. **"Under 3 sentences" is a rule for conversational turns.** A Type B explanation is the fact-led opener plus whatever Job 2 sentences bind; keep those short and plain, but the count is set by the facts that resolve, not by the persona.
3. **The greeting must not be reintroduced as a model call later.** It is the one thing the renter hears before any latency measurement starts, and a model call there would put a provider on the path to first audio — the exact thing P8 removed.
