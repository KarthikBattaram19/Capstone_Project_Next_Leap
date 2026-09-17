# Voice fix batch — hand-off (2026-09-17)

**Paste this whole file into a new Claude Code session in `C:\Capstone_Poject_Next_Leap` and say: "Apply this batch."**

It was written at the end of a session that watched five voice conversations on production. It says what is
broken, the evidence, the confirmed cause, the fix the user approved, and how to verify. **No code for this
batch has been written yet.** Production runs `9ee102d`.

---

## 0. Standing instructions for the session that applies this

- **The user has approved the whole batch** (A1–A5, B1–B3, C1–C2, D1, D2, E1–E3, F1) with the four decisions in §2.
  Apply them together; do not ask again per item. Ask only if something in the code contradicts this file.
- Read the code before changing it: the pointers below are function names and were checked at `9ee102d`.
  Line numbers drift, so search by name.
- Tests first for every fix (a failing test that reproduces the recorded sentence), then the fix.
- A peer session may write into this checkout: `git log -1` before writing, stage **by path**, never `git add -A`.
- Kill processes by PID only.
- "Done" means: backend unit suite green, frontend `vitest` + `eslint` + `tsc --noEmit` + `npm run build` green,
  eval suites A/B/C 60/60 on **three consecutive passes**, pushed, Railway serving the new commit, Vercel status
  success, and every "Replay" sentence in §3 checked on production with the replay script in §5.
- Report to the user in plain language: what changed, what was verified, what was not.

## 1. Where things stand (verified 2026-09-17 18:55 IST)

- `main` = `origin/main` = `9ee102d`, CI green, Railway SUCCESS on `9ee102d`.
- Backend unit suite at `9ee102d`: **526 passed, 1 skipped**. Frontend: **44 passed**.
- Fixed earlier today and live: spoken slot time books that slot (`b42df71`); UtteranceEnd 1500 ms (`375e239`,
  the user's decision; Task 4.1 expects L1 < 2.0 s to miss and be renegotiated with measurements);
  page state resets on a new conversation (`8409f0e`); misheard locality offers 3 closest names (`f049a77`);
  clear parts of a sentence survive a clarifying question (`9ee102d`).
- Settings the user set today (verified): Railway `JOB1_GEMINI_RPM=3000`; GitHub secret `GEMINI_API_KEY`
  (Tier 1 key). Evals cost ~146 Gemini calls per full pass.

## 2. The user's four decisions (2026-09-17)

1. **C2 — stop priming Deepgram with locality names.** Keep only the domain terms. Rely on B1/C1 name matching.
   Spec §5.1 says keyterms are "generated from the dataset's locality field": amend spec, plan and addendum in
   the same commit, dated, with the reason (conv 2: primed "Dommasandra" beat unprimed "Domlur" three times).
2. **D2 — no un-muting yet.** Add a **tap-to-stop** control while she speaks, and make E1 answers short.
   Un-muting the mic during playback is a later, measured experiment (echo caused phantom turns on 2026-09-06).
3. **E2 — parking means "parking available".** See E2 for the data facts that make "any parking" wrong.
4. **F1 — when no locality is given, ask one question first**; if the renter says anywhere, search the city and
   say how results are ordered; "better listings" gets the order explained plus orderings the data supports.

## 3. The batch

Evidence is quoted from the WebSocket recorder: **HEARD** = Deepgram's final transcript, **SAID** = the
outcome's `spoken`. Conversation times are UTC on 2026-09-17 (IST = +5:30).

### A. Understanding what the renter means

**A1 — "I can only help in English" said to English (8 times, all 5 conversations).**
- HEARD "You are giving irrelevant answers." / "I think you are not picking me correctly." / "Hello. Are you saying
  something? I did not listen from you." / "Hello" / "I cannot listen to you." / "We were already discussing about
  a listing. Right?" / "You are not acknowledging my request." → SAID "I can only help in English for now…"
- Cause (confirmed): `TurnOrchestrator._lane_a` maps every Job 1 intent `unclear` to `english_only`; Job 1 uses
  `unclear` for both other-language and did-not-understand (`scout/conversation/job1.py` `SYSTEM`, `INTENTS`).
- Fix: split the intents — `other_language` keeps today's §6.25 behaviour (incl. `ConfirmLocality`); `unclear`
  gets a plain "Sorry, I didn't follow that…" line with one example (add to `CONVERSATIONAL_REPLIES`; the persona
  sentence-cap test covers it). Update `INTENTS`, `Intent`, `JOB1_SCHEMA`, `SYSTEM`, and any eval case/assertion
  that expects `unclear` for another language (grep `evals/`).
- Replay: "You are not acknowledging my request." → not the English-only line.

**A2 — questions about a listing become requirements or a selection.**
- HEARD "Does it have a nearby hospital?" → requirement "with hospital" → Empty. HEARD "Enough. So does this have a
  lift facility?" → Empty. HEARD "So what is so special about this 2nd listing?" → SAID "Okay — the 2BHK in TC
  Palya at ₹50,000 / month. Ask me why, or say 'book it'."
- Cause (confirmed by calling `classify_turn` on the exact text → "A"): `scout/conversation/router.py`
  `_ASKS_ABOUT_LISTING` requires "this/that/the X **one**"; "it", "this listing", "the 2nd listing" miss.
- Fix: with a shortlist on screen, route to lane B: "does it/this (one|listing|flat|property|place) have …",
  "is there a … near(by)", "(this|that|the <ordinal>) (listing|property|flat|home|place)". `_ACTS` still wins
  ("show me ones with a lift" stays A). Lane B must resolve "it/this" to the listing last referred to
  (`session.focus_listing_id` / `parse_ordinal`, extend to "the 2nd listing").
- Replay (after a shortlist): "Does it have a nearby hospital?" → an answer with the hospital distance, no Empty.

**A3 — a sentence full of new requirements was treated as "why?".**
- HEARD "I don't know why you did not listen to me when I asked you to stop. Anyways, here I'm giving you a further
  filtering options. The size should be at least 1,500 square feet. It should be fully furnished. … 3 BHK or more.
  Should be having a parking facility. And it should have lift facility…" → an explanation of listing 1; shortlist
  unchanged (1,856).
- Cause (confirmed, `classify_turn` → "B"): `_EXPLAIN` matches any `\bwhy\b`.
- Fix: requirement content wins — if the text carries requirement markers (BHK, sq ft/square feet, furnished,
  parking, lift, budget/rent/lakh/k amounts, "should be", "at least") and is not a question about a listing, route A.
- Replay: the sentence above → requirements applied (readback/refined shortlist), not an explanation.

**A4 — out_of_scope used as a catch-all.**
- HEARD "I did not ask just about this property. I was asking about any other property in the Bangalore has the
  details I mentioned." and "I think you are bit not so polite. Can you be more polite?" → SAID "I only help with
  renting a flat in Bengaluru — not buying, PGs, roommates or other cities."
- Fix: Job 1 `SYSTEM` — out_of_scope only for buying, PG, roommates, commercial space, another city. Add intent
  `feedback` (complaints about her manner/answers) → a short code-built apology that restates what she can do
  (persona P-5). A search across Bengaluru is a search.

**A5 — goodbye starts a cancel.**
- HEARD "Okay. I'm ending the conversation here." → SAID "What's the six-character confirmation code?"
- Fix: intent `goodbye` → a polite close (no model beyond Job 1; nothing cancelled). Guard the cancel branch in
  `scout/conversation/voice_booking.py` `VoiceBookingFlow.handle`: `cancel` needs a cancel word ("cancel", "call
  off") plus visit/booking/appointment/code, or a code.

### B. Remembering her own questions

**B1 — answers to "Did you mean …?" and to "What's the code?" are lost.**
- HEARD "I mentioned Dommasandra." after "Did you mean Domluru or Domlur?" → added as a new locality ("in Austin Town
  or Dommasandra or Indiranagar"). HEARD "The 2nd 1, T C" after "Did you mean T.C Palya, TC Palya or S.G Palya?"
  → SAID "Which one do you mean?". Earlier run (16:45 IST): code question → HEARD "9VR7JP." → SAID "I can only help
  in English"; HEARD "I was saying 9BRJ or 7JP." → "9BRJ isn't covered".
- Cause (confirmed): the ambiguity branch in `_lane_a` returns `NeedsInput(options=…)` but stores no pending
  state; the cancel/reschedule "code" questions in `voice_booking.py` store none either. Job 1 then reads the answer
  cold, and its `unclear`/`out_of_scope` early returns run before the booking flow.
- Fix: new pending types in `scout/conversation/session.py`: `AwaitLocalityChoice(options, heard)` and
  `AwaitCode(action)`. Resolve them **in code before Job 1** at the top of `_lane_a`:
  - locality: match the text against the options only (squashed name contains/fuzzy match; "first/second/third
    one" incl. "the 2nd 1" via `normalise_ordinals`; a bare "yes" only when there is one option). Match → treat as
    `localities add <name(s)>` (C1: all names that squash alike) and continue the normal flow (readback or refine).
    Bare yes/no with >1 option → re-ask with the same buttons. Anything else → clear pending, run Job 1.
  - code: uppercase, keep only alphanumerics; exactly 6 chars from `ALPHABET` in `scout/booking/service.py`
    (`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`) → continue the cancel/reschedule with that code. Code-like tokens that do
    not make 6 → "Please say the six characters one at a time." No code-like tokens → clear pending, run Job 1.
  - Consider moving `match_offered` (slot choice, `voice_booking.py`) to the same pre-Job-1 step for consistency.
- Replay: "Did you mean T.C Palya, TC Palya or S.G Palya?" → "the second one" → readback with TC Palya.
  Cancel → "9VR7JP." → the visit read back for cancel confirmation (use a real code from a test booking).

**B2 — "No, I mentioned X" discards the correction.**
- HEARD "No. I mentioned Dommasandra." → SAID "What should I change?"
- Fix: in `_lane_a`, `confirm_no` with `ConfirmConstraints` pending and edits present → apply the edits and read back
  again, instead of "What should I change?".

**B3 — removing the only locality confirms a whole-city search.**
- HEARD "Not Domesandra." → SAID "Just to confirm — a 3BHK; rent up to ₹70,000."
- Fix: when an edit removes the last locality, ask which locality (one question, counts toward the budget).

### C. Place names

**C1 — one place, two spellings; and a regression from `f049a77`.**
- SAID "Did you mean Domluru or Domlur?", "Did you mean T.C Palya, TC Palya or N.S Palya?"; HEARD "I'm in TCPalya."
  → "TCPalya isn't covered" (asked 3 times in conv 3).
- Cause (confirmed): the bundle holds spelling variants as separate localities (T.C Palya/TC Palya; Domlur 2 /
  Domluru 8 listings — these two do not squash alike). `Job1._covered` (added in `f049a77`) refuses a squashed match
  when two names squash alike.
- Fix: in `scout/conversation/job1.py`, names that squash alike are one place — `_covered` returns all of them and
  the edits add each; `_not_covered` offers one name per squash group. For non-identical variants (Domlur/Domluru),
  group names whose squashed forms are equal after dropping a trailing "u"/"a" (verify on the 464 names that this
  merges only true variants; print the groups and check by hand). Dedupe the same way in the readback and in the
  Empty "nearby" suggestions (`scout/engines/shortlist.py`, the `"or nearby "` tip).
- Replay: "2 BHK in TCPalya under 50,000" → readback with TC Palya, no question.

**C2 — speech hints pull toward the wrong names (decision 1).**
- Evidence: Dommasandra (10 listings) is in the 60 keyterms, Domlur (2) and Domluru (8) are not; HEARD "I mentioned
  Dommasandra." three times when the renter meant Domlur (user to confirm).
- Fix: `scout/providers/deepgram_stt.py` `build_keyterms` → domain terms only; update
  `tests/unit/providers/test_keyterms.py`; amend spec §5.1 / addendum Task 2.3 / plan Task 2.3 status in the same
  commit. After deploy, confirm a live speech stream opens (boot live ping / the socket greets and transcribes).

### D. Voice and audio

**D1 — her reply is stopped before a sound (5 times, 4 conversations).**
- Recorder: `audio_out stop` 0.9–1.3 s after the renter's final words, 0 TTS bytes, and **no renter words for 5–9 s**
  (conv 1 12:59:13.4, conv 2 13:08:02.3, conv 3 13:16:23.1, conv 4 13:22:23.4). The renter, conv 3: "Hello. Are you
  saying something? I did not listen from you."
- Likely cause (**NOT confirmed**): `scout/conversation/live.py` `LiveSession._speech_started` calls `_barge_in` on a
  Deepgram SpeechStarted (sound onset, no words) while SPEAKING. The server enters SPEAKING when the outcome is
  sent, before the page receives `audio_out start` and mutes the mic, so a trailing breath/noise lands in that window.
  The same onset during THINKING has been ignored since 2026-09-10.
- Fix, in order: (1) log every barge-in with its trigger (`speech_started` vs `words`), no transcript text;
  (2) barge in during SPEAKING only on words (`_words_arrived`), not on onset alone. Keep typed barge-in.
  Update/extend `tests/unit/conversation/test_live_hold.py`.
- Verify after deploy: several turns in the browser; Railway logs show no onset-only barge-in; the recorder shows no
  `stop` without renter words.

**D2 — the renter cannot interrupt by voice (decision 2).**
- HEARD (next turn) "I don't know why you did not listen to me when I asked you to stop"; conv 4 "Enough." arrived as a
  57 s answer ended.
- Cause (confirmed): `frontend/src/app/page.tsx` mutes the mic for the whole of playback ("Mute BEFORE the first chunk
  plays").
- Fix: a visible **Stop** control while `listening === "speaking"` → `player.stop()`, unmute, and tell the server to
  cancel the rest of the reply. `scout/contract/messages.py` has only `hello` and `text` inbound: add a `stop` inbound
  message (contract schema export + `frontend/src/lib/viewmodels/contract.generated.ts`; CI runs contract-drift),
  handled in the gateway by `orch.cancel_speech`. Frontend test for the control.

### E. What she says

**E1 — the "why this one?" answer is a 36–57 s monologue.**
- SAID includes "I don't have a maintenance charge figure for this listing. I don't have a maintenance figure for this
  listing. I don't have a parking figure… lift… floor… move-in date… amenities…", "The rent is 30000 with a deposit
  of 165000", and raw names read aloud: "maintenance_charges maintenance_included parking lift floor available_from
  amenities area_basis restaurants_within_500m". Conv 4 answer: 2,718,558 PCM bytes at 24 kHz ≈ 57 s.
- Where: `_lane_b` in `orchestrator.py` speaks `" ".join([opener] + claims + gaps)`; `gaps` =
  `assembler.render_gaps()` (`scout/grounding/assembler.py`) + `job2.last_gaps` (the raw names come from there).
- Fix: speak the opener plus at most ~3 short claim sentences; gaps go to the view model/screen only, with at most one
  spoken summary ("Some details, like maintenance and parking, aren't in the listing."); never speak a raw field
  name; merge maintenance_charges/maintenance_included into one gap; give Job 2 money already formatted (₹30,000)
  in the FACTS block (`scout/conversation/job2.py`) so it copies it. Suite C grounding assertions must still pass.
- Replay: "why the first one?" → spoken text ≤ ~4 sentences, no underscores, rupee amounts formatted.

**E2 — parking (decision 3) and lift.**
- HEARD "…with a parking facility." → SAID "I didn't follow the parking required — I heard 'true'. What should I use?";
  "I'm saying I need parking also." → same with 'yes' (a loop).
- Data facts (verified in `data/bundle/listings.json`): `parking` (type) is **null for all 2,370** listings;
  `parking_available` is True 1,215 / False 1,155; `lift` is **null for all 2,370**. `data/SOURCE_NOTES.md`: the sheet
  states only whether parking exists. `scout/engines/shortlist.py` `_parking` reads `parking` only, so today every
  parking requirement matches no listing.
- Fix: a parking requirement means `parking_available == True` ("parking", "car parking", "parking facility",
  yes/true); if a type is named, say once that listings don't state the type. A lift requirement: say the listings
  don't state lifts rather than returning Empty. `reducer.py` question text (the `I didn't follow the {field}` line)
  must never speak a field name or raw model value.
- Replay: "2 BHK in HSR Layout under 50,000 with a parking facility" → readback includes parking, no question.

**E3 — Empty-result wording.**
- SAID "I found nothing matching your localities in Indiranagar — try ₹84,000, or nearby Austin Town / Domluru.";
  "I found nothing matching your localities in TC Palya — or nearby Bhattarahalli / Kittaganuru, or include the
  listings where that detail is not stated." (the unmet requirement was a hospital).
- Where: `orchestrator.py` (`nothing matching your {binding.field}`), `shortlist.py` tips.
- Fix: plain wording naming what was not found ("No 3BHK under ₹70,000 in Indiranagar."); suggest nearby localities
  only when the locality is what binds; dedupe spellings (C1).

### F. Product decision

**F1 — "best location" (decision 4).**
- HEARD "My budget is 1 lakh. I leave it to you to give me the best location. In Bangalore." → readback "rent up to
  ₹1,00,000" → 1,856 listings in 431 localities, first a ₹17,000 1BHK. HEARD "…Are there not any better listings?"
  → an explanation of listing 1.
- Facts: ranking is `_rank_key` in `shortlist.py` — soft hits, then rent ascending (cheapest first). Rent and most
  descriptive columns are randomly generated placeholders (`data/SOURCE_NOTES.md`), so "best" cannot be computed.
- Fix: no locality and no commute point → ask once "Bengaluru is big — is there an area you prefer, or somewhere you
  commute to?" before the first shortlist; if "anywhere", search the city and say the order ("cheapest first").
  "Better listings" → explain the order and offer what the data supports (largest first; nearest metro; nearest to
  the commute point). Keep this minimal; if a new ordering needs more than a small change, implement "explain the
  order" now and report the rest to the user.

## 4. Verification commands

```
# backend (from backend/)
.venv/Scripts/python.exe -m pytest tests/unit -q -p no:cacheprovider
.venv/Scripts/ruff.exe check scout tests && .venv/Scripts/ruff.exe format --check scout tests
# evals (from repo root; live Gemini + Anthropic; three consecutive passes)
backend/.venv/Scripts/python.exe -m pytest evals -q
# frontend (from frontend/)
npx vitest run && npx eslint && npx tsc --noEmit -p . && npm run build
# deploy check (from backend/, after push)
railway deployment list --json   # first entry: status SUCCESS and meta.commitHash = the pushed commit
gh run list --limit 1            # CI green
```

## 5. Tools used to observe (recreate in the new session)

**Typed replay over the production socket** — save to the session scratchpad as `ws_text_journey.py`, run from
`backend/` with `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe ws_text_journey.py "turn 1" "turn 2" …`.
`{OPT0}` is replaced by the first button of the previous reply. Stop before an email + "yes" unless a real booking is
intended.

```python
import asyncio, json, sys, time
import websockets

URL = "wss://capstoneprojectnextleap-production.up.railway.app/ws"

async def main(turns):
    t0 = time.monotonic()
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "contract_version": "1"}))
        q = asyncio.Queue()
        async def reader():
            async for m in ws:
                if not isinstance(m, bytes):
                    d = json.loads(m)
                    if d.get("type") == "outcome":
                        await q.put(d["outcome"])
        r = asyncio.create_task(reader())
        async def pump():
            while True:
                await ws.send(bytes(640)); await asyncio.sleep(0.02)
        p = asyncio.create_task(pump())
        await asyncio.wait_for(q.get(), 10)  # greeting
        opts = []
        for text in turns:
            text = text.replace("{OPT0}", opts[0] if opts else "")
            print(f"\n{time.monotonic()-t0:6.2f} >>> {text}")
            await ws.send(json.dumps({"type": "text", "text": text}))
            o = await asyncio.wait_for(q.get(), 40)
            vm = o.get("view_model") or {}
            n = sum(len(g["cards"]) for g in (vm.get("shortlist") or {}).get("groups", []))
            print(f"{time.monotonic()-t0:6.2f} <<< {o['kind']} {o.get('field','')} {o.get('options') or ''} cards={n} | {o.get('spoken')}")
            opts = o.get("options") or opts
            await asyncio.sleep(1.5)
        p.cancel(); r.cancel()

asyncio.run(main(sys.argv[1:]))
```

**In-browser recorder** (Chrome tab on `https://capstone-project-next-leap.vercel.app`, install via the
javascript tool **before** the mic is clicked; do not reload afterwards): wrap `window.WebSocket` so every string
frame in and out is pushed to `window.__rec` as `[ISO time, "IN"|"OUT", data]`, plus `CLOSE` events, bytes of binary
frames received (TTS) and binary frames sent per 10 s (mic). Read it back in slices of ~1,200 characters; the
extension blocks output containing `=`, `&`, `?` or email addresses, so strip those before returning text.

## 6. Not in this batch (recorded, not approved)

- Earlier afternoon run: "Did the PDF also go to the owner?" → out_of_scope; "Have you sent the previous PDF?" →
  English-only. A4 and A1 may cover the misroutes; what she should *say* about the PDF/owner is unanswered.
- Un-muting the mic during playback (D2 later experiment).
- The user has not confirmed whether both confirmation emails (codes FUM2U2, 9VR7JP) arrived.
- Open from earlier: browser rows 6.13, 6.14, 6.15 (Firefox), 6.21 cancel-by-code half, 6.42, Firefox rows;
  Task 4.1 latency report; Task 4.3 sign-off; `Docs/ERROR_WALKTHROUGH.md` and `Docs/Implementation_Plan.md` status
  updates for today's fixes.
