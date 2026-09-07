# Gate L — Latency (DECIDED 2026-09-06: PROCEED WITH RENEGOTIATION)

> **Measured on 2026-09-06 against the deployed service. Every row missed its original
> target; the scorer said `passed: false`.** Nothing below is estimated. **Decision:
> PROCEED WITH RENEGOTIATION**, taken on the user's instruction to complete the gate with
> the proposed table. Spec §5.2, the addendum's Global Constraints, the plan's speed rule
> and `evals/latency/score.py` were changed in the same commit as this tick.
>
> **Re-scored against the renegotiated table, the same 50 runs still do not pass**, and the
> reason is sample size, stated plainly: with n = 25 per type, nearest-rank p99 is the
> **maximum** sample, so one slow run sets the row. Six p99 rows still exceed the new
> targets — A/L0 3,284 and B/L0 1,957 (one slow interim each; medians 1,344 / 1,343),
> B/L1 2,448 (median 1,764), B/L3 3,903 (median 2,712), and A/L4 11,295 / B/L5 15,101
> (the two transit stalls; medians 3,527 / 4,818). One 2× violation remains: A/L4 11,295
> against a 10,000 cap. Medians and p90 sit inside every new target. So the table is
> accepted on the medians and p90, and the p99 rows are **re-taken at n ≥ 100 per type**
> with the real Type B recording as the first Phase 2 measurement — where p99 is the 99th
> of 100 and a single stall no longer decides it. That re-run is an obligation, not a hope.
>
> **Region: US only, by decision, not by measurement (2026-09-06).** The Singapore row
> stays blank. A Bengaluru client is roughly 200–250 ms from a US region against roughly
> 40–60 ms from Singapore; every provider hop pays that, so the region choice is a real
> part of the misses below and cannot be separated from them without the second service.

Skeleton commit: `3e26c72`. Client location: Bengaluru (the user's machine; assumed from
project context, not measured). Runs: 25 per turn type, one region (US), sequential,
each run a fresh browser-equivalent session.

**Recordings.** Type A: `data/raw/utterance_a_16k.wav` (sha256 `8f932358ac872d18…`),
the user's own voice, 16 kHz mono PCM16, 5.12 s, peak 52 % FS, spoken fluently (longest
internal pause 80 ms) — *"I'm looking for a 2 BHK in Koramangala under 40,000 rupees,
and I need parking"*. It carries **500 ms of trailing silence inside the file**, which the
driver counts as speech, so the Type A L1/L2/L4 figures below are understated by about
0.5 s. **Type B is PROVISIONAL: synthesised speech** (Smallest.ai, resampled to 16 kHz),
because no Type B recording existed at run time. Re-run the B rows when it does.

| Region | L0 p99 | L1 p99 | L2 p99 | L3 p99 | L4 p99 | L5 p99 | 2× violations | cold start L1 |
|---|---|---|---|---|---|---|---|---|
| us (A / B) | 3,284 / 1,957 | 1,910 / 2,448 | 3,085 / — | — / 3,903 | 11,295 / — | — / 15,101 | 50 of 50 runs (see below) | **3,150** (A, first turn on a fresh container; warm median 1,251) |
| singapore *(not deployed — comparison skipped by decision)* | — | — | — | — | — | — | — | — |

Targets (spec §5.2): L0 300 · L1 700 · L2 1,500 · L3 1,500 · L4 3,000 · L5 6,000 ms. Every
cell above exceeds its target at p99; **every one of the 50 runs also breaks the 2× rule**
on L0 (all 50 > 600 ms) and on L1 for every Type B run (all 25 > 1,400 ms).

**Medians and p90, so the p99 outliers do not hide the shape (ms, client-measured):**

| | L0 | L1 | L2 / L3 | L4 / L5 |
|---|---|---|---|---|
| Type A median · p90 | 1,344 · 1,568 | 1,251 · 1,455 | 2,783 · 2,940 | 3,527 · 4,347 |
| Type B median · p90 | 1,343 · 1,593 | 1,764 · 1,885 | 2,712 · 2,912 | 4,818 · 5,317 |

**Per-component (server traces, ms after the ack, 25 turns each):**
`external.groq` 622 median / 700 max · Smallest.ai `tts.first_byte` **865 median** after
the text is ready (both types, 1,005 max) · Anthropic `llm.first_token` 1,285 median /
1,615 max · `llm.last_token` 2,979 median / 3,580 max. The server finishes every Type A
turn ≤ 1,726 ms and every Type B turn ≤ 3,580 ms after the ack.

**Where the time goes, in order.**
1. **End-of-speech detection: ~1.75 s** from the last word to the ack (Type B L1 median
   1,764; Type A reads 1,251 only because of the file's trailing silence). The turn
   fires on Deepgram `UtteranceEnd` (utterance_end_ms = 1000), not on the 400 ms
   endpoint, because the 400 ms endpoint split a sentence at a natural breath on real
   speech (2026-09-06; see plan Task 0.9). This is the single largest term and it is a
   **deliberate deviation from P3 as worded**; `speech_final` at a 1,000 ms endpoint was
   measured to save 0.4 s and to split a 1.1 s breath 4 of 4 times on production, and
   was reverted.
2. **TTS first byte: 865 ms** from a US region to Smallest.ai, on both turn types. With
   the ack this alone consumes the whole L3 budget.
3. **First interim from Deepgram: ~1.3 s** after the first frame (L0). Not tunable on
   our side; it is provider behaviour plus the US round trip.
4. **Two transit stalls** in 50 runs: Type A L4 max 11,295 and Type B L5 max 15,101 while
   the server had finished those turns in 1,726 / 3,580 ms — the delay was on the wire to
   the client, not in any provider. They set the p99 for L4 and L5 on their own.

**Cold start (spec §6.56, reported separately, never averaged in).** Measured 2026-09-06 14:54 UTC on
a container with zero prior turns (log checked), first turn Type A: L0 1,537 · **L1 3,150** · L2 4,755 ·
L4 6,093 ms — a **+1.9 s** penalty against the warm medians, landing almost entirely in L1 (the Deepgram
socket and first-use TLS to each provider). The second turn on the same container (Type B, synthesised)
was already near warm: L1 2,159 · L3 2,758 · L5 4,532. Rows in `latency/spike-cold.jsonl`.

False end-of-speech rate on the Type A utterance: **0/20** — all 20 plays transcribed
identically and whole, one turn each. On this speaker the endpointing did not cut.

Preconditions in force during the runs:
- **P1 ✓** — `railway.json` `sleepApplication: false`, read by Railway (build log shows
  `backend/Dockerfile` from it); no run was a cold start.
- **P2 partial** — one Deepgram socket and one client per provider per session, but the
  spike opens a **new session per run**, so each run paid a fresh TLS handshake to every
  provider that a real conversation pays once. Provider figures above are therefore
  slightly pessimistic.
- **P3 ✗ as worded / P3b ✓** — `endpointing=400` and `utterance_end_ms=1000` are both sent,
  but the turn is triggered by UtteranceEnd (P3b), not the 400 ms endpoint. See item 1.
- **P4 ✓** — TTS is called per sentence; the Type B opener goes alone.
- **P5, P6 n/a** — no OSM, no calendar in the skeleton.
- **P7 ✓** — Job 2 runs `thinking: adaptive` with `output_config.effort` set explicitly.
- **P8 ✓** — the opener's first byte lands 865 ms after the ack, 420 ms before Job 2's
  first token and ~2.1 s before its last.

## Decision

- [ ] PROCEED — every row meets its target at p99 with no 2× violation. Region: US (chosen by decision, not measurement — see the note at the top). **Not available: every row missed.**
- [x] PROCEED WITH RENEGOTIATION — rows that missed: **all of L0, L1, L2, L3, L4, L5.** Spec §5.2 table, the addendum's Global Constraints, the plan's speed rule and the scorer's targets updated **in the commit that ticks this box** (`git log -1 --format=%h -- data/GATE_L.md`).
- [ ] CHANGE THE MODEL — Job 1 missed L1/L2; switch `JOB1_MODEL` to ___ and re-run. **Not indicated: Job 1 (Groq) took 622 ms median, 700 max — it is not where the time goes.**

### Decision taken (the table below is now spec §5.2)

**PROCEED WITH RENEGOTIATION** was ticked on this reading of the numbers: the misses are not
caused by the models — Job 1 is fast and Job 2's first token is inside its budget — but by
three things the spec's table did not price in: ~1.75 s of end-of-speech detection that
tolerates a breath, ~0.9 s of TTS first byte from a US region, and ~1.3 s to Deepgram's
first interim. A renegotiated table should price those in **and** name what Phase 2 must
reclaim, so the budget is not quietly ignored.

§5.2 values as amended, p99 with the 2× rule unchanged, derived from component medians
plus headroom rather than from this run's maxima:

| Stage | Was | Now | Derivation |
|---|---|---|---|
| L0 first interim | 300 | **1,800** | Deepgram first interim ~1.3 s + US RTT; p90 1.6 s. |
| L1 ack | 700 | **2,000** | UtteranceEnd ~1.75 s after the last word + RTT. This run's Type B p99 (2,448) would still fail it — one sample; re-run with the real Type B recording. |
| L2 first audio, A | 1,500 | **3,500** | L1 + Groq 0.6 + TTS 0.9; p90 2.9 s. |
| L3 first audio, B | 1,500 | **3,500** | L1 + TTS 0.9; p90 2.9 s. |
| L4 shortlist rendered | 3,000 | **5,000** | p90 4.3 s; the 11.3 s sample was a transit stall. |
| L5 explanation rendered | 6,000 | **8,000** | p90 5.3 s; the 15.1 s sample was a transit stall. |

**What Phase 2 must try to reclaim, written into the plan as obligations, not hopes:**
(a) end-of-speech: `speech_final` at a 1,000 ms endpoint saves 0.4 s if the false
end-of-speech count on more speakers stays at 0 — the orchestrator (Task 2.10) can also
merge a late second final into the running turn instead of cancelling it; (b) TTS first
byte: a Singapore region would cut every provider round trip by ~200 ms — the comparison
was skipped by decision and can be reopened; (c) session reuse inside the spike so P2 is
actually in force when the numbers are re-taken.

**If you would rather not renegotiate this far**, the only lever that changes the numbers
materially before Phase 1 is deploying the Singapore service and re-running — roughly a
few hundred rupees for a day and ~30 minutes.

Tick exactly one. If renegotiating, edit `Docs/Problem_Statement_Detailed.md` §5.2 **and**
the plan's Global Constraints in the same commit — a budget quietly ignored is the
failure mode the spec names.

---

## How this was filled in

**Prerequisites (all met on 2026-09-06).**

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

---

## Footer — OSM routing coverage (Task 1.3, recorded 2026-09-07)

The addendum's Task 1.3 Step 4 asks for this note here. The precompute ran the fixed
eight-query set for all 2,370 listings (18,960 rows) through the OSM MCP server on
2026-09-07. Of the 16,590 nearest-X rows, 11,024 found a place and **every one of them was
routed** (OSRM public server; 0 straight-line fallbacks), so routing covered **100 %** of
listing-anchored queries where OSM had a node — above the ≥ 90 % threshold. 5,566 rows are
null (no node within the query radius; the MCP server returns nodes only, so amenities
mapped as areas are invisible). Consequence for the demo: precomputed transit claims say
"by route"; "in a straight line" will only ever be heard for the tenant's own commute
point (live, computed from coordinates). Routed rows carry no duration (the public OSRM
ignores the foot profile), so speech gives a distance by route, never a walking time.
