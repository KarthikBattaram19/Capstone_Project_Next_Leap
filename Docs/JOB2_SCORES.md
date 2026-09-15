# Job 2 — the model decision and its score (Task 2.13)

**Status (2026-09-15, 23:08 IST): the model is pinned and Suite C is measured — 20/20 on three
consecutive passes of all three suites (60/60 ×3) on `37a3333`.** See "Sign-off passes"
below. Nothing in this document is estimated: a row is either a measurement with its date,
or it says "not run".

## The pin

| | |
|---|---|
| Model id | `claude-sonnet-5` (exact id, never a `latest` alias — spec §5.1) |
| Where it is set | `Settings.job2_model` in `backend/scout/config.py` |
| `output_config.effort` | `low` (P7), `Settings.job2_effort` |
| Sampling parameters | none. `temperature`, `top_p` and `top_k` do not exist on `messages.stream` in anthropic 1.3.0, so the rule is enforced by the SDK, not only by us |
| Assistant prefill | none |
| Response shape | fixed by `output_config.format` = `JOB2_SCHEMA` |
| Different from Job 1 | yes — Job 1 is Gemini `gemini-3.5-flash-lite` (since 2026-09-10; Groq `openai/gpt-oss-120b` before that). Falling back from Job 2 to Job 1 for an explanation is forbidden; a Job 2 failure produces `Degraded`, never a substitute |

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
| Suite C, sign-off passes 1-3 | **20 / 20, 20 / 20, 20 / 20** (2026-09-15, `37a3333`) | three consecutive full passes, below; before them five runs on successive builds found and fixed five defects (see "The night of 2026-09-14/15") |
| Suite A | **20 / 20 ×3** (2026-09-15, same three passes on `37a3333`) | plus 20/20 ×2 on 2026-09-14 (`bbaa68b`) and 20/20 on 2026-09-10 |
| Suite B | **20 / 20 ×3** (2026-09-15, same three passes on `37a3333`) | plus 20/20 ×2 on 2026-09-14 (`bbaa68b`); the 2026-09-10 timeouts did not recur |
| Dropped sentences per case | **measured 2026-09-15**, table below | 55 bound, 9 dropped on the last run; the new `unsupported` reason caught 2 mis-citations, zero `unknown_ref` |
| L3 / L5 from traces | **component timings read from the three passes; L3 and L5 themselves cannot be scored from eval traces** | the harness has no audio, no STT and no browser, so there is no end-of-speech, no `tts.first_byte` and no "rendered" moment. What the traces do give is under "Sign-off passes". L3/L5 proper come from the production timed interactions (Task 4.1) |
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

## The night of 2026-09-14/15 - a revoked key, two green suites, and five Suite C defects

**Pass 2 (23:36 IST, `bbaa68b`): A 20/20, B 20/20, C 7/20 with zero sentences bound in
every case.** The Anthropic key had been revoked on the provider side (HTTP 401 "API key
is invalid"; the same key had answered on 2026-09-10 and `backend/.env` was unchanged
since 2026-09-09). Every Job 2 call failed, every lane B turn degraded, and nothing said
so: the log carried only the 13 grounding assertions that followed, and the seven cases
with no prose expectation passed on degraded turns. 146 of the day's 500 Gemini calls
went on it. Fixed in `1bb5ed1`: a preflight pings both providers before a run and aborts
naming the provider and status; a `Job2Down` is logged with its reason and carried on
`Degraded.why`; Suite C accepts `Answered` only; `Settings.__repr__` redacts secrets
(pytest had printed the first fifty characters of the key under each failure).

**Pass 3 (23:50 IST, A and B only): 40/40.** Suites A and B do not touch Job 2. With the
fresh key (supplied just after midnight) Suite C ran five times on successive builds:

| Run | Build | Result | The one defect it found | Fix |
|---|---|---|---|---|
| 1 | `1bb5ed1` | 17/20 | c-013 cited `computed:…:straight_line`, the tenant's own commute row, a ref kind the assertion did not know; c-008 and c-017 merged a listing fact or a second passage into a one-passage sentence | `0e64959`: the assertion learns `computed`; the prompt says one passage per sentence, listing facts in their own |
| 2 | `0e64959` | 19/20 | c-018 wrote "the neighbourhood guides themselves don't actually discuss deposit amounts", a gap as prose, citing two passages that say none of it | `0511917`: the assembler drops a sentence about what the documents do not say (`gap_assertion`) |
| 3 | `0511917` | 19/20 | c-008 restated passage 0-2 word for word and cited passage 0-1 (right words, wrong ref) - the same shape as run 1 | `692e7bf`: the assembler applies Suite C's support test to every cited passage and drops the sentence (`unsupported`) |
| 4 | `692e7bf` | 19/20 | c-013: "I work in Whitefield" came back from Job 1 as a locality edit; the shortlist emptied and "why the first one?" asked "Which one do you mean?" | `0bc73c8`: the Job 1 prompt says where they travel to is a commute point; live probe 3/3 |
| 5 | `0bc73c8` | 19/20 | c-008: "nearest park is" matched inside "nearest park isn't available", a correct denial | `2aa2499`: the case forbids the shape of an invented distance (`must_not_match`), not those words |

Runs 3-5 each cost 42 Gemini calls (41 Type A turns and the preflight). The day's budget
closed at roughly 466 of 500, so the three consecutive runs on `2aa2499` start after the
12:30 IST reset: `python -m pytest evals/suites/test_suite_c.py -q` three times, ~4 min
and 42 calls each. Any failure means a fix and three fresh runs.

**Grounding held throughout.** Across the five runs Job 2 never cited a ref outside its
bundle (`unknown_ref` 0 everywhere). Run 5's table:

```
  c-001        3 bound    2 dropped   no_refs=2
  c-002        3 bound    1 dropped   unsupported=1
  c-003        6 bound    0 dropped   -
  c-004        4 bound    1 dropped   no_refs=1
  c-005        3 bound    1 dropped   unsupported=1
  c-006        2 bound    0 dropped   -
  c-007        3 bound    0 dropped   -
  c-008        2 bound    0 dropped   -
  c-009        2 bound    0 dropped   -
  c-010        0 bound    0 dropped   -
  c-011        1 bound    0 dropped   -
  c-012        4 bound    1 dropped   no_refs=1
  c-013        3 bound    1 dropped   no_refs=1
  c-014        0 bound    1 dropped   no_refs=1
  c-015        3 bound    0 dropped   -
  c-016        1 bound    0 dropped   -
  c-017        5 bound    0 dropped   -
  c-018        1 bound    1 dropped   no_refs=1
  c-019        4 bound    0 dropped   -
  c-020        5 bound    0 dropped   -
  TOTAL       55 bound, 9 dropped
```

`unsupported` is the row to read now, next to `unknown_ref`: it is a sentence whose cited
passage does not contain what it says. Two in twenty cases on run 5, both fenced.

**Not done, deliberately.** The two 2026-09-14 passes of Suites A and B ran on `bbaa68b`;
the commits since touch the eval harness, Job 1's commute rule, the Job 2 prompt and the
assembler, none of the Suite A/B logic - but sign-off wants three consecutive runs of all
three suites on one build, so the A/B passes are evidence, not the sign-off record. Also:
the CI `evals` job now runs on `workflow_dispatch` only, one matrix run at a time, and
needs a `GEMINI_API_KEY` repository secret that does not exist yet (`gh secret list`
shows only GROQ and ANTHROPIC).

## Sign-off passes, 2026-09-15 evening - 60/60 three times

Build `37a3333` (code identical to `2aa2499`; the commit on top is documentation). Command,
from the repo root, one pass after the other with nothing else using the Gemini project:
`LATENCY_LOG_PATH=latency/evals-signoff-passN.jsonl python -m pytest evals -q`. Each pass
collects 130 tests: Suites A, B and C (20 each) plus 70 harness, assertion and scorer tests.

| Pass | Started (IST) | Result | Wall time | Job 2 sentences |
|---|---|---|---|---|
| 1 | 22:32 | **130 passed** - A 20/20, B 20/20, C 20/20 | 11 m 06 s | 51 bound, 6 dropped (`no_refs` 5, `unsupported` 1) |
| 2 | 22:44 | **130 passed** - A 20/20, B 20/20, C 20/20 | 11 m 31 s | 54 bound, 7 dropped (`no_refs` 7) |
| 3 | 22:56 | **130 passed** - A 20/20, B 20/20, C 20/20 | 10 m 48 s | 53 bound, 2 dropped (`no_refs` 2) |

**`unknown_ref` was 0 in every case of every pass**: Job 2 never cited a reference outside its
bundle. `gap_assertion` was 0 throughout; `unsupported` fired once (pass 1, c-008). Every
pass's preflight reached both providers. The three passes spent 438 Job 1 calls
(146 each, counted from the `external.gemini` spans) of the day's 500.

Per-case table, pass 3:

```
  c-001        3 bound    0 dropped   -
  c-002        2 bound    0 dropped   -
  c-003        5 bound    0 dropped   -
  c-004        0 bound    1 dropped   no_refs=1
  c-005        4 bound    0 dropped   -
  c-006        4 bound    0 dropped   -
  c-007        1 bound    0 dropped   -
  c-008        2 bound    0 dropped   -
  c-009        3 bound    0 dropped   -
  c-010        0 bound    0 dropped   -
  c-011        1 bound    0 dropped   -
  c-012        4 bound    0 dropped   -
  c-013        0 bound    1 dropped   no_refs=1
  c-014        6 bound    0 dropped   -
  c-015        1 bound    0 dropped   -
  c-016        1 bound    0 dropped   -
  c-017        5 bound    0 dropped   -
  c-018        1 bound    0 dropped   -
  c-019        5 bound    0 dropped   -
  c-020        5 bound    0 dropped   -
  TOTAL       53 bound, 2 dropped
```

A case with 0 bound can still pass: its assertions are the declared gap and what must not be
said (c-010 asks "when can I move into the first one?"; `available_from` is null on every
slice listing, so the right answer is the declared "move-in date" gap, and the case forbids
"available immediately" / "ready to move").

**Component timings from the three passes' traces** (498 turns: 438 Type A, 60 Type B; none
cold). Measured from the start of the server-side turn, so they exclude speech recognition,
audio and rendering - they are components, **not L3 or L5**:

| Component | n | median | p99 | max |
|---|---|---|---|---|
| Type B: turn start → Job 2 first token | 60 | 2,497 ms | 4,302 ms | 4,302 ms |
| Type B: turn start → Job 2 last token | 60 | 6,301 ms | 11,237 ms | 11,237 ms |
| retrieval | 60 | 97 ms | 1,221 ms | 1,221 ms |
| Job 1 (`external.gemini`, includes the 15-a-minute pacer's wait) | 438 | 1,353 ms | 6,696 ms | 13,491 ms |

**A risk this shows, not yet a measured miss:** L5 (question end → full explanation
rendered) has an 8,000 ms target, and Job 2's last token alone came after 8 s on **5 of 60**
Type B turns (8,773 / 9,526 / 9,002 / 9,526 / 11,237 ms). None exceeds the 16,000 ms 2× hard
limit. On production L5 also includes end-of-speech detection, so the p99 there will be
higher than these. Task 4.1's production run decides whether L5 is renegotiated; the Job 1
numbers are not Gate L figures because the free-tier pacer sits inside the span.

## The hybrid-retrieval trigger (arch §9.1, not fired)

Dense retrieval is in use. The documented trigger to graduate to hybrid retrieval is a Suite
C failure on an **exact-token** question — a society name, a road name — where the right
chunk exists but dense similarity did not surface it. No such failure has been observed in
three consecutive 20/20 passes (2026-09-15). **Do not build hybrid retrieval until this row records a real
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
