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
| Dropped sentences per case | **not logged** | the assembler drops silently today; the counter is added when the suite first runs |
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

**What has to change before this document can be completed:** a Groq tier whose daily token
allowance covers at least one suite run (three for sign-off), or a Job 1 model whose
per-call cost is materially lower. This is an account decision, not a code change.

## The hybrid-retrieval trigger (arch §9.1, not fired)

Dense retrieval is in use. The documented trigger to graduate to hybrid retrieval is a Suite
C failure on an **exact-token** question — a society name, a road name — where the right
chunk exists but dense similarity did not surface it. No such failure has been observed,
because the suite has not run. **Do not build hybrid retrieval until this row records a real
failure.**

## Notes for whoever completes this

- Run `python -m pytest evals/suites/test_suite_c.py -q` three times and record each count.
- The assembler's drop count is what tells you whether Job 2 is being fenced or is simply
  writing uncitable prose. Log it from `ClaimAssembler.bind` before the third run.
- If a case flakes, the fix is Job 2's prompt or the case wording. Never loosen an assertion.
