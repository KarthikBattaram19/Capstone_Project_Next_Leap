# Job 2 — the model decision and its score (Task 2.13)

**Status: the model is pinned; the Suite C score is NOT YET MEASURED.** This document is
written as the record it will be, with the unmeasured rows marked. Nothing below is
estimated: a row is either a measurement with its date, or it says "not run".

## The pin

| | |
|---|---|
| Model id | `claude-sonnet-5` (exact id, never a `latest` alias — spec §5.1) |
| Where it is set | `Settings.job2_model` in `backend/scout/config.py` |
| `output_config.effort` | `low` (P7), `Settings.job2_effort` |
| Sampling parameters | none. `temperature`, `top_p` and `top_k` do not exist on `messages.stream` in anthropic 1.3.0, so the rule is enforced by the SDK, not only by us |
| Assistant prefill | none |
| Response shape | fixed by `output_config.format` = `JOB2_SCHEMA` |
| Different from Job 1 | yes — Job 1 is Groq `openai/gpt-oss-120b`. Falling back from Job 2 to Job 1 for an explanation is forbidden; a Job 2 failure produces `Degraded`, never a substitute |

## What has been measured

**Live single-turn check — passed, 2026-09-09.**
`backend/tests/integration/test_job2_live.py` resolves a real `FactBundle` from
`backend/tests/fixtures/bundle_min` (Koramangala listing, 8 OSM rows, 2 guide chunks),
streams `Job2.explain`, and asserts that at least one sentence binds through the
`ClaimAssembler` and that **no sentence cites a ref outside the bundle**. It passed on the
first run against `claude-sonnet-5`.

That is the grounding boundary working end to end on the real model. It is not a Suite C
score.

## What has NOT been measured

| Run | Result | Why |
|---|---|---|
| Suite C, run 1 | **ran 2026-09-10, does NOT count** | 20/20, but five cases were vacuous - see "The evening run" |
| Suite C, run 2 | **not run** | |
| Suite C, run 3 | **not run** | |
| Suite A, best complete run | **20 / 20** (2026-09-10, on Gemini) | first clean run; the "1274 sq ft" defect from 2026-09-09 stayed fixed |
| Suite B, any run | **17 / 20** (2026-09-10) | first run that ever completed. All three failures were one cause: a Gemini read timeout, twice per case. Not a refinement defect |
| Dropped sentences per case | **measured 2026-09-10** | 48 bound, 11 dropped across Suite C, every drop `no_refs`. Zero `unknown_ref`: Job 2 never cited outside its bundle |
| L3 / L5 from traces | **not measured** | needs a suite run |
| Groq-hosted alternative for Job 2 (spec §5.1) | **not run** | needs a Suite C baseline to compare against |

**Why the suite has not run.** Every Suite C case begins with two Type A turns — the
preferences and the "yes" that confirms the readback — and those go through Job 1 on Groq.
On 2026-09-09 the Groq account reached its **daily** token limit:

```
Rate limit reached for model `openai/gpt-oss-120b` ... on tokens per day (TPD):
Limit 200000, Used 199358, Requested 1512. Please try again in 6m15.84s.
```

One Job 1 call costs 1,315–1,512 tokens (measured from the 429 bodies: the system prompt,
the strict schema and the reasoning completion). The three suites are 60 cases of about 2.5
turns each — roughly 150 calls, about **210,000 tokens per run**, and sign-off asks for
three consecutive runs. On the current 200,000-tokens-per-day tier a single run does not
fit, let alone three.

**Update, later the same day:** `reasoning_effort="low"` was adopted (see the Phase 2 exit note in `Docs/Implementation_Plan.md`). It cuts the call to 886 tokens used / ~1,020 reserved, so one run now costs ~154K and fits inside a day — one run per day, three days for sign-off, or one sitting on Groq's paid tier for about $0.09.

Capping `max_completion_tokens` was tried as a way to shrink the reservation and rejected:
`gpt-oss-120b` is a reasoning model that spends completion tokens before it writes the
JSON, so a 512-token cap cut the reply off mid-object and Groq rejected its own generation
against the strict schema. The transport now retries four times honouring `Retry-After`,
which absorbs the per-minute limit (8,000 TPM) but cannot absorb a daily one.

**What has to change before this document can be completed:** a Groq tier whose daily token
allowance covers at least one suite run (three for sign-off), or a Job 1 model whose
per-call cost is materially lower. This is an account decision, not a code change.

## Job 1 moved to Gemini (2026-09-10)

Job 1 runs on `gemini-3.5-flash-lite` (`JOB1_PROVIDER=gemini`), not Groq. Measured on the
same probe set: 6/6 correct, 0.99 s median against Groq's 1.50 s, 399 tokens a call against
886. Job 2 is unchanged — `claude-sonnet-5` on Anthropic — so the two jobs remain different
models on different providers.

**Gemini free-tier limits, read off the 429 bodies:**

| | |
|---|---|
| Requests per minute | **15** (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`) |
| Requests per day | **500** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`) |
| Job 1 calls in one 60-case pass | **151** |
| Passes affordable per day | **3** (453 calls), with ~47 calls of headroom |

The client paces under the per-minute cap rather than retrying into it, because a rejected
request still counts against both quotas. This is why the three sign-off passes must be run
on a clean day: debugging runs spend the same 500.

For comparison, Groq's free tier afforded 1.3 passes a day (200,000 tokens at ~1,020 a
call). Gemini affords 3.

## The evening run, 2026-09-10 - one valid pass, three defects found

Job 1 on Gemini, 151 calls, **zero 429s**: the per-minute pacer held for a whole pass.

| Suite | Result |
|---|---|
| A | **20 / 20** |
| B | **17 / 20** - b-008, b-013, b-020 |
| C | **20 / 20, but not a valid 20/20** - see below |

**Suite B's three failures were one cause, and it was not the refinement logic.** All three
returned `Failed(capability="understanding")` from `GeminiError: ReadTimeout from Gemini`,
each having timed out **twice** - the single retry then in place could not save them. Two
timeouts in a row on three separate cases is what a dead pooled connection looks like: the
retry went back out over the socket that had just hung.

**Suite C's 20/20 was hollow.** The new drop counter is what exposed it: five cases bound
zero sentences - c-005, c-008, c-010, c-018, c-019. Their questions ("is there a park near
the first one?", "when can I move into the first one?") matched none of the router's
explanation patterns, so they went to lane A, which produces no explanation at all. Suite C
guarded its whole grounding block with `if vm.explanation is not None`, so
`assert_every_claim_cites`, `gaps_declared` and `must_not_mention` were **skipped, not
passed**. Four of the five are contamination probes. Read that run as **15 cases tested, 5
vacuous**.

On the 15 that did run, grounding held: **48 sentences bound, 11 dropped, every drop
`no_refs`, zero `unknown_ref`.** Job 2 did not once cite a reference outside its bundle.

**Fixed the same evening, none yet verified against the live provider:**

| Commit | Fix |
|---|---|
| `139639a` | A question that names a listing ("the first one") routes to lane B. Verified across all 122 case turns: exactly those five change lane, nothing regresses B to A. Also a real product bug - a renter asking about a park got no explanation |
| `139639a` | A case declaring `gaps_declared` or `must_not_mention` now fails when no explanation exists, instead of quietly checking nothing |
| `6453602` | A Gemini timeout drops the pooled connection before retrying; three attempts, and the read timeout falls from 30 s to 12 s (worst case 60 s to 36 s, with more chances) |

**Two later passes produced nothing.** Pass 2 was killed at ~60% after running into the
daily ceiling - its rising failure count was quota, not code. Pass 3 aborted on its quota
probe before spending a call. The day's 500 went on one valid pass, one killed pass, a
concurrent session's own run, and debugging.

**On the fixed build a pass costs 146 Job 1 calls** (five turns moved from Job 1 to Job 2),
so three sign-off passes are 438 of 500 - it fits, with 62 spare and no room to re-run a
failed pass the same day. **The 500 is per project, not per session:** two sessions sharing
this checkout spent it between them on 2026-09-10.

## The hybrid-retrieval trigger (arch §9.1, not fired)

Dense retrieval is in use. The documented trigger to graduate to hybrid retrieval is a Suite
C failure on an **exact-token** question — a society name, a road name — where the right
chunk exists but dense similarity did not surface it. No such failure has been observed,
because the suite has not run. **Do not build hybrid retrieval until this row records a real
failure.**

## Notes for whoever completes this

- Run `python -m pytest evals/suites/test_suite_c.py -q` three times and record each count.
- The assembler's drop count is what tells you whether Job 2 is being fenced or is simply
  writing uncitable prose. **It is now counted automatically (2026-09-10)** — no longer
  something to remember before the third run. `ClaimAssembler` counts every sentence it
  binds and every one it drops, by reason (`no_refs`, `unknown_ref`, `gap_assertion`);
  lane B accumulates the counts on the session and logs one line per Type B turn; and a
  Suite C run prints a per-case table in its terminal summary. Paste that table in here.
  Counts and reasons only — the dropped sentence is never stored or logged (spec §5.3).
  `unknown_ref` is the row to watch: it means Job 2 cited a reference that was not in the
  bundle, which is a fabricated citation the fence caught.
- If a case flakes, the fix is Job 2's prompt or the case wording. Never loosen an assertion.
