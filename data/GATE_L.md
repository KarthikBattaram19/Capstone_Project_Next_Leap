# Gate L — Latency (NOT YET DECIDED)

> **This gate is open.** Nothing below has been measured. The driver and scorer exist
> (`scripts/latency_spike.py`, `evals/latency/score.py`) and are tested, but they have
> not yet been run. The service **is** deployed and verified (2026-09-06:
> `/health` 200 in 0.96 s; a typed-fallback Type A turn on the deployed `/ws`
> returned `outcome: answered` with 238 KB of audio). What is missing is the two
> recorded utterances the driver replays.
>
> **Region: US only, by decision, not by measurement (2026-09-06).** The plan asked
> for a US and a Singapore service so the region could be chosen on evidence. The
> user chose to run one service and skip the comparison. The Singapore row below
> therefore stays permanently blank, and if the US numbers miss their targets it is
> **not known** whether Singapore would have passed — a Bengaluru client is roughly
> 200–250 ms from a US region against roughly 40–60 ms from Singapore, so that gap
> is large enough to matter. Any renegotiation of spec §5.2 decided from these
> numbers carries this caveat.
>
> **No box may be ticked from an unmeasured run.** Every cell below is blank on
> purpose. Filling them in requires the four commands in *How to fill this in*.
> Until one box is ticked, Phase 0 has not exited and no Phase 1 work may begin
> (plan §4, spec §9.2).

Skeleton commit: `<sha>`. Client location: `<city>`. Runs: 25 per turn type. One region (US).

| Region | L0 p99 | L1 p99 | L2 p99 | L3 p99 | L4 p99 | L5 p99 | 2× violations | cold start L1 |
|---|---|---|---|---|---|---|---|---|
| us-… | | | | | | | | |
| singapore *(not deployed — comparison skipped by decision)* | — | — | — | — | — | — | — | — |

Per-component (from the server traces): `stt.final`, `external.groq`, `llm.first_token`, `tts.first_byte` …

False end-of-speech rate on the Type A utterance: `<k>`/20.

Preconditions in force during the runs: P1 ✓/✗ · P2 · P3 · P4 · P5 · P6 · P7 · P8 (state each, with evidence).

## Decision

- [ ] PROCEED — every row meets its target at p99 with no 2× violation. Region: US (chosen by decision, not measurement — see the note at the top).
- [ ] PROCEED WITH RENEGOTIATION — rows that missed: ___. Spec §5.2 table updated in commit ___ and this plan's Global Constraints updated to match.
- [ ] CHANGE THE MODEL — Job 1 missed L1/L2; switch `JOB1_MODEL` to ___ and re-run (numbers below).

Tick exactly one. If renegotiating, edit `Docs/Problem_Statement_Detailed.md` §5.2 **and**
the plan's Global Constraints in the same commit — a budget quietly ignored is the
failure mode the spec names.

---

## How to fill this in

**Prerequisites, none of which are met yet.**

1. ~~Provider keys in `backend/.env`~~ **met** — the three live pings passed 2026-09-05, and `SMALLEST_VOICE_ID` is set on Railway (the deployed turn speaks).
2. ~~A deployed backend~~ **met** — one Railway service (US), verified live 2026-09-06.
   The Singapore service was deliberately not created (see the note at the top). Still
   outstanding on it: set `LATENCY_LOG_PATH=/tmp/latency.jsonl` so the server-side
   per-component traces exist, and confirm **App Sleeping is OFF** (P1) before timing
   anything — a sleeping service measures its own cold start every run.
3. Two recorded utterances, 16 kHz mono PCM16 WAV, **an Indian-English speaker if at all
   possible** — P3's 400 ms endpointing is unmeasured on that speech, which is the whole
   reason the false end-of-speech count below exists:
   - Type A: *"two BHK in Koramangala under forty thousand, need parking"*
   - Type B: *"why did you pick this one, is the commute realistic"*

**Then run, warm (not on the first request after a deploy):**

```
python scripts/latency_spike.py --url wss://capstoneprojectnextleap-production.up.railway.app/ws --wav-a a.wav --wav-b b.wav --runs 25 --label us
python -m evals.latency.score latency/spike-us.jsonl
```

The scorer prints `p99`, `counts`, `violations` and `passed`. Copy the numbers into the
table above; `passed: false` means one of the two lower boxes, never the first.

**Three measurements the scorer does not make for you.**

- **Cold start.** Redeploy, wait for healthy, run *one* turn, record its L1 in the table's
  last column. It is reported separately and never averaged into the budget (spec §6.56).
- **False end-of-speech rate.** Play the Type A utterance 20 times and count how many `ack`
  lines lost the words after the natural pause (*"…under **forty thousand**"*). This is the
  number that says whether P3's 400 ms holds on Indian-English speech.
- **Preconditions P1–P8.** State each with evidence, not assertion — the Railway sleep
  setting, the trace spans, the `endpointing`/`utterance_end_ms` actually sent.

**How the scorer decides.** Two independent rules, and a run must satisfy both:

- **p99 per stage per turn type** — nearest-rank, so with 100 samples it is the 99th. A
  single slow request does **not** move it; that is p99 working as defined ("the time
  within which 99 of every 100 requests finish", plan §2).
- **The 2× rule** — any *single* request over twice its target is a hard failure on its
  own. This is what catches the outlier p99 ignores.

Type A and Type B are scored separately and never averaged: Type B meeting L3 does not
excuse Type A missing L2.
