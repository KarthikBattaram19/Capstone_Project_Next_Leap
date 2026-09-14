# Voice-based AI Property Scout — Bengaluru

A voice-first rental assistant that collects a tenant's spoken preferences, shortlists real Bengaluru listings, **explains every choice with citations**, and books a site visit on Google Calendar for both tenant and owner.

The problem it addresses isn't finding listings — it's judging whether one fits your life. Is the commute realistic? What's the area actually like? Is the extra room worth the extra rent? Every answer this system gives is traceable to a source, and where it has no source it says so.

> **Status: Phases 0–3 built (2026-09-10), evals in sign-off (2026-09-15) — see `Docs/Implementation_Plan.md`.** Booking, cancel and reschedule work by voice and over HTTP against the real Google calendars; the confirmation PDF is emailed and discarded. Suites A and B passed 20/20 twice in a row on 2026-09-14; Suite C found and fixed five defects over five runs on 2026-09-15 and its three consecutive runs on the final build are queued for the next Gemini quota day (`Docs/JOB2_SCORES.md`). Not yet done: the sign-off record and Phase 4.

---

## The documents

**[`Problem_Statement_Detailed.md`](./Docs/Problem_Statement_Detailed.md) (v3.10) is the single source of truth.** Scope, data schema, latency budget, all 58 error cases, and the sign-off contract live there — and it governs wherever this README, the architecture, or any summary disagrees with it.

**[`Architecture.md`](./Docs/Architecture.md)** is how the system is structured to meet it — components, data model, turn lifecycles, error taxonomy, and the decisions taken with their alternatives.

**[`Implementation_Plan.md`](./Docs/Implementation_Plan.md)** is the build plan as a decision document — plain language: the 39 tasks in five phases, why that order, what "done" means for each, and a table of every decision the owner will be asked to make (the two gates, the model pins, the region). Its companion, **[`Implementation_Plan_Addendum.md`](./Docs/Implementation_Plan_Addendum.md)**, is the technical reference builders work from: for every task, the files, interfaces, tests and step-by-step instructions.

| You are about to… | Read |
|---|---|
| Orient, or set up | this README |
| Decide **what** correct behaviour is | the specification — §6 for failure behaviour, §7.3 for what "done" means |
| Decide **where** code goes, or **how** something is shaped | the architecture — §5 for components, §4 for the data model, §12 for decisions already taken |
| Decide **what to build next**, or take a gate decision | the implementation plan — §4 for the order, §5 for the decisions |
| **Build** a task | the addendum, at that task's number |

The architecture is *derived* from the specification, and the plan from both; none is independent. If they disagree, the specification wins and the others are wrong.

---

## What it does

- **Meet Nakshatra** — the assistant greets you the moment you click the microphone, says who she is and what she can do, and asks for your preferences with an example. Warm, plain-spoken, at most three sentences a turn ([`Architecture.md` §11.2](./Docs/Architecture.md))
- **Speak your requirements** — *"2BHK in Koramangala, budget 35k, need parking, close to a metro."* Constraints are always confirmed back before a shortlist is generated.
- **Refine by voice** — *"drop anything above 40k."* Only the affected part changes; everything else keeps its place.
- **Ask why** — every neighborhood claim carries a citation; every distance names the method that produced it.
- **Book a visit** — dual-calendar booking with a confirmation code, cancel and reschedule by voice, PDF emailed on confirmation.

---

## Architecture

```mermaid
flowchart LR
    B["Browser<br/>(Vercel)"] -- "WebSocket: mic audio" --> S["Backend<br/>(Railway)"]
    S -- "shortlist + citations" --> B
    S <--> D["Deepgram<br/>STT"]
    S <--> G["Groq · Job 1<br/>extraction"]
    S <--> A["Anthropic · Job 2<br/>grounded explanation"]
    S <--> T["Smallest.ai<br/>TTS"]
    S <--> C["Google Calendar<br/>+ Gmail"]
    S --- L["Static dataset ·<br/>guide index ·<br/>precomputed OSM"]
```

**Every provider call originates on the backend.** The browser talks to exactly one origin and holds no keys. The dataset, the closed guide index and all OpenStreetMap values are resolved at **build time** and served from local storage — no source fetching, no retrieval fetching and no OSM lookups happen inside a tenant's turn.

Three structures carry most of the correctness, and are worth knowing before reading any code — all detailed in [`Architecture.md`](./Docs/Architecture.md):

- **`Provenanced<T>`** — every fact travels with its source, method, timing and as-of date. A distance without its method label is *unrepresentable*, not merely discouraged
- **The resolver registry** — the grounding boundary is a call graph, so the explanation model can only reach facts through a resolver
- **`TurnOutcome`** — "nothing found" and "couldn't ask" are different variants of a union, so they cannot accidentally render alike

The full set — fifteen guardrails, each against the section that actually enforces it — is indexed in [`Architecture.md` §17.3](./Docs/Architecture.md).

### Two LLM roles, two providers

The pipeline uses two models because the two jobs have opposite requirements:

| Job | Model | Why |
|---|---|---|
| **1 — Extraction & edit routing** | Groq `openai/gpt-oss-120b` | Latency-critical, sits inside the 700 ms acknowledgment budget. Needs schema conformance, not reasoning |
| **2 — Grounded explanation** | Anthropic `claude-sonnet-5` | Decides whether the zero-hallucination bar is met. Off the critical path — capability beats speed |

Both are pinned by **exact model ID, never a `latest` alias** — the CI guarantee is void if the model can change underneath the suite.

---

## Stack

| Layer | Choice |
|---|---|
| Speech-to-text | Deepgram (keyterm boosting, endpointing 400 ms with a content-aware hold) |
| LLM | Groq + Anthropic (see above) |
| Text-to-speech | Smallest.ai, streaming |
| Maps / transit | OpenStreetMap MCP — [jagan-shanmugam/open-streetmap-mcp](https://github.com/jagan-shanmugam/open-streetmap-mcp) |
| Calendar & email | Google Calendar + Gmail, single OAuth |
| Listings source | `data/Bangalore_Properties_List.xlsx` — a supplied spreadsheet, imported once |
| Frontend host | Vercel |
| Backend host | Railway |

---

## Planned structure

```
.
├── .github/workflows/ci.yml            # unit, contract-drift, frontend build, evals ×3
├── .env.example                        # every secret name, empty
├── Docs/
│   ├── Problem_Statement_Detailed.md      # the specification
│   ├── Problem_Statement_Summary.md       # condensed working summary
│   ├── Architecture.md                    # how it is structured
│   ├── Implementation_Plan.md             # the build plan — decisions, order, done-when
│   └── Implementation_Plan_Addendum.md    # per-task technical reference for builders
├── data/
│   ├── raw/                            # ignored: raw HTML, guide pages, MCP responses
│   ├── SOURCE_NOTES.md                 # what the supplied spreadsheet publishes
│   ├── GATE_D.md · GATE_L.md           # the two written gate decisions
│   ├── guides/sources.json             # 1–3 guide URLs per locality
│   └── bundle/                         # committed, versioned, read-only at runtime
│       ├── manifest.json               # DatasetManifest — the sign-off record
│       ├── listings.json               # curated ListingRecord[]
│       ├── osm_facts.json              # OsmFactRecord[] — every listing × every query
│       ├── chunks.json                 # GuideChunk[] (the citable text; Chroma holds vectors)
│       └── chroma/                     # persisted ChromaDB, one collection per locality
├── contract/v1.schema.json             # exported JSON Schema of the wire contract
├── scripts/
│   ├── google_auth.py                  # one-time OAuth: prints the refresh token
│   └── latency_spike.py                # Gate L driver against the deployed skeleton
├── backend/                            # Railway — pipeline, both LLM jobs, calendar, PDF
│   ├── pyproject.toml · Dockerfile · railway.json
│   ├── scout/
│   │   ├── main.py                     # create_app(); boot check runs before the port opens
│   │   ├── config.py                   # Settings (pydantic-settings) — all secrets, model ids
│   │   ├── domain/                     # provenance, listing, osm, guides, manifest, constraints, shortlist, booking
│   │   ├── contract/                   # the versioned wire contract: outcome, view-models, messages, http, export
│   │   ├── platform/                   # artefacts (bundle loader), boot checks, telemetry
│   │   ├── providers/                  # thin wrappers: deepgram, groq, anthropic, smallest, google calendar, gmail
│   │   ├── engines/                    # amounts, reducer, shortlist, commute, availability, slots
│   │   ├── conversation/               # session, hold, router, persona, state, orchestrator
│   │   ├── grounding/                  # retrieval, resolvers, opener, assembler
│   │   ├── booking/                    # service, reconcile, pdf
│   │   ├── presentation/viewmodel.py   # the only thing the browser receives
│   │   ├── api/                        # ws (mic gateway), http (bookings, health, contract, admin)
│   │   └── pipeline/                   # offline build: import_sheet, curate, gap_report,
│   │                                   #   chunking, build_index, precompute_osm, manifest
│   └── tests/unit/ · tests/integration/
├── evals/
│   ├── fixtures/                       # frozen slice: listings, chunks, OSM facts
│   ├── harness/driver.py               # text in → TurnOutcome out, no audio
│   ├── assertions/                     # view-model, provenance, order matchers
│   ├── cases/a/ · cases/b/ · cases/c/  # 20 JSON cases each
│   ├── suites/test_suite_a.py · test_suite_b.py · test_suite_c.py
│   └── latency/score.py                # p99 per stage per turn type; 2× rule
└── frontend/                           # Vercel — Next.js draws view-models, holds no keys
    ├── src/app/                        # routes (page.tsx only; NO api/ directory)
    ├── src/lib/audio/                  # capture worklet, player, unlock, barge-in
    ├── src/lib/transport/              # WebSocket + HTTP clients, contract check
    ├── src/lib/viewmodels/contract.ts  # generated from contract/v1.schema.json
    ├── src/lib/state/session.ts        # mirrors the backend session
    └── src/components/                 # cards, snapshot, sources, mic, booking, failures
```

---

## Getting started

### Prerequisites

Every secret is **set on the backend**; none belongs in the frontend or in the repo. The
boot check refuses to start, naming every missing value at once, if any is absent.
`.env.example` lists them all.

| Variable | Source |
|---|---|
| `DEEPGRAM_API_KEY` | [deepgram.com](https://deepgram.com) |
| `GEMINI_API_KEY` (with `JOB1_PROVIDER=gemini`, the default) or `GROQ_API_KEY` (with `JOB1_PROVIDER=groq`) | Job 1; only the selected provider's key is required |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) — Job 2 |
| `SMALLEST_API_KEY`, `SMALLEST_VOICE_ID` | [app.smallest.ai/dashboard](https://app.smallest.ai/dashboard) |
| `GOOGLE_OAUTH_CREDENTIALS` | printed once by `python scripts/google_auth.py <client_secret.json>` (Calendar + Gmail send scopes) |
| `GOOGLE_TENANT_CALENDAR_ID`, `GOOGLE_OWNER_CALENDAR_ID`, `GOOGLE_SENDER_EMAIL` | the demo account's two secondary calendars and its address |
| `OPERATOR_TOKEN` | any secret string; guards `POST /admin/availability` |
| `CORS_ALLOWED_ORIGINS` | comma-separated explicit allowlist; `*` is refused |

The frontend takes exactly one backend-related variable, and it is public, not a secret:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | The Railway backend URL |

### Build order

The build is ordered by **what can invalidate what**, not by what is satisfying to build. Two things can still prove the design wrong, so both are settled first — **in parallel**, each behind a gate. The rationale is §9 of the specification; the task-by-task plan is [`Implementation_Plan.md`](./Docs/Implementation_Plan.md).

**Phase 0 — de-risk (both tracks at once)**

1. **Data** — import and curate up to 10 listings per locality; publish the locality list, counts and total; document the availability marker and which schema fields the supplied spreadsheet actually carries.
   *Gate:* a missing marker or a thinner-than-assumed schema means **stop and amend the spec** — it changes the filter vocabulary, the cards and the eval coverage.
2. **Infrastructure** — deploy a **walking skeleton** to Railway and Vercel (health check, mic WebSocket, one stub turn touching every provider) and run the **latency spike on it**, comparing candidate regions.
   *Gate:* confirm the latency budget against measurement or renegotiate it in writing. **This has to run on real infrastructure** — measured locally it tells you nothing about the cross-provider, cross-region reality the budget is made of.

**Then, in order**

3. **Knowledge layer** — the listing-scoped guide index, and the OSM query set run once across every listing with attribution and retrieval date.
4. **Eval harness and the view-model contract** — deliberately before the features they test: Job 2 is validated *against Suite C*, so Suite C exists first, and the card/citation view-model is a contract shared by the suite, the backend and the UI.
5. **Voice pipeline**, then **shortlist and refinement**, then **grounded explanation**.
6. **Booking, PDF and email**, then the **UI**, then hardening and sign-off.

### Running it locally

```powershell
# Backend (Python 3.12). The lock file carries the dev tools too (pytest, ruff).
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e .
copy ..\.env.example .env        # then fill every value
python -m pytest tests/unit -q   # unit suite; the committed bundle is loaded from a copy
python -m scout.main             # boot checks first; exits 2 naming any missing secret

# Frontend (Next.js). NEXT_PUBLIC_API_URL is baked in at build time.
cd frontend
npm install
npm run contract                 # regenerates the types from contract/v1.schema.json
npm test
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev

# Eval suites (need the Job 1 and Job 2 keys; each run costs model quota)
python -m pytest evals -q
```

Booking without the microphone: `POST /bookings/slots`, `POST /bookings`,
`POST /bookings/{code}/cancel`, `POST /bookings/{code}/reschedule` — bodies in
`contract/v1.schema.json`; the 6-character code is the only credential, and an unknown
code and a cancelled one get the same answer.

---

## Deployment

Deployment happens **twice**: a walking skeleton in Phase 0, so the latency budget can be measured on real infrastructure, and the full application later — the same two targets, promoted rather than replaced.

**Backend first, frontend second** — the two hosts deploy independently, so version skew is possible in production even when CI is green. The backend exposes a contract version and the frontend pins the one it expects.

**Railway (backend)**
- App sleeping **off** — a sleeping instance wakes on the tenant's first word and misses every latency target
- One long-lived process, holding the Deepgram WebSocket and keep-alive pools
- Healthcheck endpoint configured
- Region chosen by measurement, not intuition — the backend makes many round trips to providers but holds only one stream to the browser

**Vercel (frontend)**
- Static/SSR only — **no API routes.** Serverless functions can't hold the persistent connections the latency budget depends on
- Preview deployments create new origins; include them in the CORS allowlist deliberately or restrict the backend to production

CORS is an **explicit allowlist, never `*`**. The mic WebSocket goes browser → backend directly, never proxied.

---

## Testing

Three suites, 20 cases each, **60 total at 100% pass, run three times** — locally, or in CI by `gh workflow run ci.yml` (the `evals` job is manual-only and serial: Job 1's free-tier Gemini quota is 500 calls a day for the whole project and a pass is ~146 of them). A run pings both providers first and aborts before spending a call if either refuses.

| Suite | Checks |
|---|---|
| **A — Feasibility** | Shortlist respects budget, bedrooms and must-haves; ≥1 case per schema field; `null` handling |
| **B — Edit correctness** | Untouched listings and their order are **byte-identical** before and after a voice edit |
| **C — Grounding** | Citations resolve to the correct listing-scoped source; gaps declared; injection and cross-locality contamination probes |

Latency is instrumented per component and scored at p99, **separately per turn type**. See §7.3 of the full statement for the complete sign-off contract.

---

## Non-negotiables

If you contribute one thing to this codebase, know these:

1. **Never fabricate to cover a gap.** *"I don't have that"* is always a correct answer. A fluent answer with no source behind it is the worst failure this system can produce.
2. **"Couldn't ask" and "nothing found" must never look alike.** An empty shortlist because nothing matched is a *result*; an empty shortlist because a service failed is an *error*. Rendering them identically is the likeliest way this system misleads someone.
3. **Every distance names its method.** *"About 15 minutes to the metro"* is a red-line failure. A straight-line figure heard as a travel time understates a Bengaluru commute enough to change someone's decision — so the words *by route* or *straight line* are mandatory, in speech and on the card.
4. **`null` is a real value, and it never satisfies a must-have.** Unstated fields read *"not stated"* — never blank, never zero, never inferred. Unknowns surface as their own group rather than being silently dropped or silently counted.
5. **Imported text and retrieved chunks are untrusted data**, delimited in prompts and never executed as instructions.
6. **Slot arithmetic is always `Asia/Kolkata`**, never server-local time. The backend is deliberately hosted outside India.
7. **Never ask a renter for personal or financial details.** Rent, deposit and budget are the only money topics. The single exception is the email address at the confirmation step, because the PDF cannot be sent without it — read back letter by letter, used once, and gone with the session. Extraction has no field to hold anything else, so this survives a prompt edit.

---

## Out of scope (MVP)

Login and accounts · post-visit feedback · cross-session preference history · mobile app · languages beyond English · production-grade privacy compliance.

Owner contact is the labelled placeholder `999999999` throughout — deliberately not a valid Indian mobile number, so nothing in a demo can dial a real person.
