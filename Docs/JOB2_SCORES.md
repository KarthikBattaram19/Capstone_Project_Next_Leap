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
| Suite C, run 1 | **not run** | see below |
| Suite C, run 2 | **not run** | |
| Suite C, run 3 | **not run** | |
| Suite A, best complete run | **18 / 20** (2026-09-09, with `reasoning_effort=low`) | both failures were one defect — a size arriving as "1274 sq ft" — since fixed; the re-run exhausted the day's allowance |
| Suite B, any run | **0 / 20 completed** | every case failed with Job 1 down on a 429, not on anything it asserts |
| Dropped sentences per case | **instrumented, not yet measured** | the counter exists as of 2026-09-10 (below); it has no values until a suite run produces them |
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
