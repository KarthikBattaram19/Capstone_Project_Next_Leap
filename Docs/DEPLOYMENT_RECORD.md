# Deployment record

Written 2026-09-10 at the end of Phase 3 (Task 3.7). Everything below was measured or
read from the live services on that date unless it says otherwise. Where a step has not
happened yet it says so; nothing here is a plan dressed as a fact.

## The two public URLs

| Service | URL | Host |
|---|---|---|
| Backend | `https://capstoneprojectnextleap-production.up.railway.app` | Railway, one always-on process |
| Frontend | `https://capstone-project-next-leap.vercel.app` | Vercel, static build, no API routes |

Both answered on 2026-09-10: `GET /health` → `{"status":"ok","contract_version":"1"}` in
0.98 s from this machine; the Vercel page returned HTTP 200.

## What production is running, and what it is not

Railway builds from the GitHub repository on every push to `main`, using
`backend/Dockerfile` (`railway.json` at the repository root). On 2026-09-10 `origin/main`
stood at commit `7a14afc` (2026-09-09, an OSM precompute fix). **That is Phase 1 code.**
Every Phase 2 task (the conversation) and every Phase 3 task (booking, PDF, email, the
finished UI) exists only in commits that have not been pushed. The promotion in Task 3.7
Steps 1–3 therefore happens on the next push to `main`, backend first, and is recorded
in the section *Promotion checklist* below rather than claimed here.

## Region, and the numbers behind it

**Railway region: US.** Chosen by decision on 2026-09-06, not by measurement: the Singapore
service was deliberately not created, so the comparison Gate L asked for was never run.
`data/GATE_L.md` records the caveat and the measured US numbers (25 runs per turn type,
client-measured, one region). Gate L was decided *proceed with renegotiation* and spec
§5.2 was amended in the same commit; the renegotiated targets are the ones every later
measurement is scored against:

| Row | Target (renegotiated) |
|---|---|
| L0 first feedback | < 1.8 s |
| L1 acknowledgement | < 2.0 s |
| L2 / L3 first audio (A / B) | ≤ 3.5 s |
| L4 shortlist rendered | < 5 s |
| L5 explanation rendered | ≤ 8 s |
| L6 booking confirmed | < 5 s |
| L7 cancel / reschedule | < 5 s |
| L8 PDF + email | < 30 s |

The p99 table itself, the cold-start figure (first turn 3,150 ms) and the two transit
stalls that set L4/L5 alone are in `data/GATE_L.md`; they are not repeated here so there is
one place to correct them.

## App sleeping and health check

`railway.json`: `sleepApplication: false` (precondition P1), `healthcheckPath: /health`,
`healthcheckTimeout: 60`, `restartPolicyType: ON_FAILURE`, one replica. The build log on
2026-09-06 showed `load build definition from backend/Dockerfile`, which is the evidence
that `railway.json` is being read and the sleeping setting is in force. No keep-warm ping
is used or needed.

## CORS allowlist in force

`CORS_ALLOWED_ORIGINS` on Railway is exactly two origins:

```
https://capstone-project-next-leap.vercel.app
http://localhost:3000
```

Vercel preview deployments are **not** added. Verified 2026-09-10 against the live
backend with `GET /contract`:

| Request `Origin` | Result |
|---|---|
| `https://evil.example` | HTTP 200, **no** `access-control-allow-origin` header |
| `https://capstone-project-next-leap.vercel.app` | HTTP 200, `access-control-allow-origin: https://capstone-project-next-leap.vercel.app` |

Two things this does not prove, carried from Task 0.9: browsers do not apply CORS to
WebSockets, so the mic socket works regardless of the allowlist; and the allowlist is
what the plain-HTTP booking routes (`POST /bookings…`, Task 3.3) depend on, which is why
it is checked on its own evidence.

## Versions

| What | Value | Where it is pinned |
|---|---|---|
| Contract version | `1` | `backend/scout/contract/__init__.py`; `contract/v1.schema.json` (32 `$defs`); checked in the first WebSocket frame and by the CI drift job |
| Bundle version | `1` (must equal the contract version; the boot check refuses otherwise) | `data/bundle/manifest.json` |
| Listings / localities | 2,370 / 464 | manifest |
| OSM facts | 18,960 rows (2,370 × 8), `osm_index_date` 2026-09-09 | manifest |
| Embedding model | `all-MiniLM-L6-v2`, fingerprint `onnx:sha256:4f148ba8ae9c2c7f` | manifest; compared to the loaded weights at boot |
| Job 1 | `JOB1_PROVIDER=gemini` by default (`GEMINI_API_KEY`), Groq `openai/gpt-oss-120b` behind `JOB1_PROVIDER=groq` | `backend/scout/config.py`, `.env.example` |
| Job 2 | `claude-sonnet-5`, effort low | `backend/scout/config.py` |
| Python | 3.12.10, every dependency pinned in `backend/requirements.lock` | `backend/pyproject.toml` |

## Promotion checklist (Task 3.7 Steps 1–3, to run on the push)

The push to `main` is the promotion. Before it, the Railway variables must carry every
name the boot check demands, or the deploy fails its health check and the previous
version keeps serving (which is the intended failure mode):

1. `GEMINI_API_KEY` and `JOB1_PROVIDER=gemini` (or `GROQ_API_KEY` with
   `JOB1_PROVIDER=groq`), `SMALLEST_VOICE_ID`, and the four Google values
   (`GOOGLE_OAUTH_CREDENTIALS`, `GOOGLE_TENANT_CALENDAR_ID`,
   `GOOGLE_OWNER_CALENDAR_ID`, `GOOGLE_SENDER_EMAIL`) plus `OPERATOR_TOKEN` — all were
   already required in Phase 0 except the Job 1 provider pair, which arrived with Phase 2.
2. Push. Watch the Railway build log for `load build definition from backend/Dockerfile`,
   then the boot: a passing boot prints nothing before uvicorn's `Started server process`;
   a failing one prints every missing name and exits 2.
3. `curl https://capstoneprojectnextleap-production.up.railway.app/health` → status ok,
   contract version `1`.
4. Only then let Vercel build the frontend from the same push (`NEXT_PUBLIC_API_URL` is
   already inlined; it needs no change unless the backend URL changes). Open the page,
   click the microphone: the hello frame must be answered (no close code 4400) and the
   greeting must be spoken.
5. Repeat the two `Origin` requests above; the foreign origin must still get no
   `access-control-allow-origin` header.
6. One real booking by voice on the production URL, then a cancel by code — the Phase 3
   exit line.

## Evidence gathered locally on 2026-09-10 (the same code the push will deploy)

Against `python -m scout.main` on this machine with the operator's `backend/.env`, the
real Google account, over HTTP:

| Step | Result |
|---|---|
| `POST /bookings/slots` | 3 slots, first at 11:00 IST the same day, 1.80 s |
| `POST /bookings` | booked, `calendar_sync: complete`, 2.54 s (L6 < 5 s); the event was found on **both** calendars by an independent lookup |
| `POST /bookings/{code}/reschedule` | moved to the next hour on both calendars, same code, 3.88 s (L7 < 5 s); the same slot again → "nothing changed"; a typed `Tuesday at 4 pm` → Tuesday 15 September at 4 pm |
| `POST /bookings/{code}/cancel` | 1.67 s; both calendars empty afterwards and still empty 35 s later (after a reconcile tick) |
| Cancelled code vs unknown code | identical `404` with `No matching visit was found for that code.` |
| `POST /admin/availability` | 401 without the operator token, 200 with it |
| Email | server log: `confirmation email sent for booking <code>` (the address is never logged) |

Two defects were found by this walk-through and fixed before the commit, both recorded in
the code: the two parallel calendar writes shared one `httplib2` transport, which is not
thread-safe (6 of 6 warm parallel inserts failed with TLS record errors) — each worker
thread now has its own; and a cancel did not purge a queued repair for the same code, so
a half-landed booking came back on the Owner calendar 30 s after being cancelled — the
queue is now purged before any cancel or move.
