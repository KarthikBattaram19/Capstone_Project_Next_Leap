# Architecture — Voice-based AI Property Scout, Bengaluru

## 1. Preface

**The problem.** Renters do not struggle to *find* listings. They struggle to judge whether a listing fits their life — is the commute realistic, is the area safe, is the extra room worth the extra rent.

**The system.** A voice-first AI property scout for **Bengaluru only**. You talk to it. It collects your preferences by voice, shortlists listings imported from the supplied spreadsheet `data/Bangalore_Properties_List.xlsx` (**up to 10 per area** — the specification's word is *locality* — a ceiling, not a target), explains every choice and names a source for it, and books a site visit on Google Calendar for both you and the owner.

**The five things it must do:**

1. Collect your preferences and **read them back to you for confirmation** before shortlisting (at most 5 clarifying questions).
2. Change the shortlist when you ask ("drop anything above 40k") **without disturbing the listings you did not mention, or their order**.
3. Explain each choice, with a source for every neighbourhood claim — and say plainly when it has no data.
4. Book, cancel and reschedule visits, using a **6-character code** instead of a login.
5. Email a PDF confirmation.

---

## 2. The big picture

### 2.1 Who talks to what

```mermaid
flowchart TB
    T["Renter<br/><i>speaks, listens, reads</i>"]
    OP["Operator<br/><i>runs the build, holds the Google login</i>"]

    subgraph SYS["Voice Property Scout"]
        direction TB
        FE["Frontend — Vercel<br/><i>screen and microphone</i>"]
        BE["Backend — Railway<br/><i>all the thinking</i>"]
        BUILD["Build pipeline"]
    end

    subgraph LIVE["Live services — called during a conversation"]
        DG["Deepgram<br/><i>speech to text</i>"]
        GQ["Groq<br/><i>fast model, Job 1</i>"]
        AN["Anthropic<br/><i>careful model, Job 2</i>"]
        SM["Smallest.ai<br/><i>text to speech</i>"]
        GC["Google Calendar<br/>and Gmail"]
    end

    subgraph OFFLINE["Data sources"]
        BR["Supplied spreadsheet<br/><i>listings</i>"]
        OSM["OpenStreetMap<br/><i>metro, bus, amenities</i>"]
        WK["Wikipedia and city guides<br/><i>neighbourhood character</i>"]
    end

    T <--> FE
    FE <--> BE
    OP --> BUILD
    BUILD --> BR & OSM & WK
    BUILD -.->|"packaged files"| BE
    BE <--> DG & GQ & AN & SM & GC

    classDef person fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef ours fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef live fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef offline fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    class T,OP person
    class FE,BE,BUILD ours
    class DG,GQ,AN,SM,GC live
    class BR,OSM,WK offline
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp9VWtP2zAU_StWkPYpsD6gaBWqRCmNGK_RMtC27sONc5NYdezMdnho23_fddOUQMWsKsq1fc59nvR3wHWCwZAFqdSPPAfj2O14oRit2x-LYIbKoTmKzcfRkRjZEmFpQyaFdajoxSAk9uijGC2CnzXo-guhrks04PQGZyplmcuRxZWQSchyLZN6I9I6k8ikzoTa8NRMtoozA2XO5t_mxHmnBUf2xWjids9sznXlNl79SoRB7oRWmwT8mp4Sdmo0paEStqh6ne4-u0PDUW6y4gZRMaDzQnBykGuFr5Lya-yJxsCXLZ4ZCPkIzw0RSLlKyuVCLYXKtjm-nl1MPI0vAytFiVIo3Fwh5q3kL87uvOML8YDMonmgItjGPSeHmLCkMuSMAeNaPaCx4Ivwyu8kIooJYkmcRauZyHPmNHP45LZijW4IExn9q7mfgnWsoGmRIfusY9bdghxfEeRYuZxqKHiD42AwrWQb2tuCzi8JOi98QtbtgWjAPjQfYh3sdpAnPsh6hk5AUgGhHjrfzKig9vy3uNfT6cXZla_vBBwwqyuaC_u6ZTM6jVFlICtT7RnSQxObVwEV3m5Fdb3KhkSg5o5Gy11C2WAKdEaHpAMSDxSohBO4TXB_Tvh7saQBSQSsJpMLGvqsEgldX3MpFFkeU8y51nSBtAvci7XN1sr6lh3t7o5IELU5Pa3t8WkjXLYy_YjWO6vXenPGPvis6Hl__upwb3f0ZxGUJAvIaBRTIX39_mxYx2svk4iw0Q09jq_osaKKTprQuARrJ5gy0rYlARONHO4kMUKKoaWKLXG40zsY9DFem7uPInH5sFc-hVxLbYY7nbgb9-ENHxXHNmw85Xi4YesOoL8P77Md9LA7eMMmvQhrthTTPn9hSz4dHnYG77LtH3Sh038bW5p69a8JMcFPrWQPeR8weZeQgusMDlqE7DakBtbla29PT8Mx_VbN8sVon02iMLoJj6_C-WUYnayyax-PZyG1PLw_byINQhZkRiT0b-FMhWQVaEhjfiP47aGLgD5_BX3QhvRKUlwugoX663ElqO9aFy9Qo6ssJzMFab1dlQk4nAjwn6iXa1A5PX9WfL3z9x-IFxg6) — zoom, pan and export</sub>

### 2.2 The three moving parts

| Part | Where it runs | What it is responsible for | What it must never do |
|---|---|---|---|
| **Frontend** | Vercel | Draws what the backend sends it; captures the microphone; plays the audio stream | Hold a key, call a provider, run an API route, or work out a fact for itself |
| **Backend** | Railway — **one process that stays awake** | Runs the conversation, both model jobs, retrieval, filtering, booking, PDF and email | Fetch from listing sites or OpenStreetMap while a renter is waiting |
| **Build pipeline** | The operator's machine or CI, **offline** | Import, curate, gap-report, build the guide index, precompute OpenStreetMap facts, write the manifest | Run during a conversation |
| **Artefact bundle** | Plain files, versioned alongside the code | The dataset, the guide index, the OpenStreetMap facts, the manifest | Change without a version bump |

**[AD-1] The build pipeline is a separate program, not something the backend does at start-up.** It writes versioned files that the backend only ever reads. This keeps the dataset reproducible, makes the field-availability gap report (spec §9.1) a real deliverable, and means an import failure can never take the service down in the middle of a demo.

### 2.3 One conversation, end to end

```mermaid
flowchart LR
    A["<b>1. Speak</b><br/>microphone to<br/>live transcript"] --> B["<b>2. Understand</b><br/>fast model turns words<br/>into requirements"]
    B --> C["<b>3. Choose</b><br/>plain code filters<br/>and ranks listings"]
    C --> D["<b>4. Explain</b><br/>careful model phrases<br/>facts it is handed"]
    D --> E["<b>5. Book</b><br/>free slot, two calendar<br/>entries, 6-character code"]
    E --> F["<b>6. Confirm</b><br/>PDF emailed"]

    classDef s1 fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef s2 fill:#cffafe,stroke:#0891b2,stroke-width:2px,color:#083344
    classDef s3 fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef s4 fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef s5 fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#4c0519
    classDef s6 fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    class A s1
    class B s2
    class C s3
    class D s4
    class E s5
    class F s6
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp11Mlu2zAQANBfGShX27GsxQsCA_GSUw9Fg15S9UCRQ4swRaokVacI8u-llsiCAevkGYlvhkPJHwHVDIMNBFzqCy2IcfDtR6bAX8-_suAp34YzeK2QnJ8e8-1Tbh63paBGV4VWCE63GSn--t-GKEuNqFwW_IbpdAu7DljM4KdiaKwjig0KJ9ZB6YtLcLVRFi7aMNveEsppMPinFgZLVM56sGtp17r7zo1msC-0tjiYlSRCQbMj4EI6X7JN-7LgmztbkMI6oU5XcN-Chw6MZ3B8b41BpMQgr2XfaFUYYtH2_VNnQTgQFgpfAdmAHlr02KHJDHZaX6fHDSJYqd0E3EUDJRIVI6a95_dqBNoJpNPmKHwFNO12BvrY0i8dnfoBaMWFKQf9--EFsCRC9u10q6gk1h6Qgw2bwcjNA8uRcJxYZ_QZNw-LJI0w78PpRTBXbBbV-4Rqqc3mYZ6HeURurUVvUc7H1ny1DvPFfWsVRXF8a0VffVFOcTlYYUqimNy3kgWG6a0V9xZHHtGrxdbL5Ty9a8VJSObRrZV8WRxjTAcLw5DFq_sWnSfh-tZKewsZrkfzWtKIILtr-R3O02RkwbM_xnG880cxjvd-nOP44Ecyjo9-W-P4xbcWTCA4GcH8P4EzNfqoROPfoyYRfDRPZ4Er_NeY-UQW-Bf2nAWZ-mzWVUS9aV1elxpdnwofciJtE9cVIw4PgpwMGT1Gaqdf_ynaZz7_Ax-TdNI) — zoom, pan and export</sub>

Steps 3 and 5 are **ordinary code, not a model**. That is deliberate: filtering, ranking, availability and slot arithmetic have right answers, so they are written as functions that can be tested, not asked of a model that might answer differently next time (**A4**, §17).

### 2.4 Two kinds of turn

Everything said to the system is handled as one of two turn types. They have different speed budgets because they call different providers.

```mermaid
flowchart TB
    Q["Renter speaks"] --> R{"What kind<br/>of request?"}
    R -->|"'2BHK under 40k'<br/>'drop anything above 35k'"| TA["<b>Type A</b><br/>speech, fast model, filter<br/><i>Groq only</i>"]
    R -->|"'why this one?'<br/>'what is the area like?'"| TB["<b>Type B</b><br/>speech, look up facts,<br/>careful model, check citations<br/><i>adds Anthropic</i>"]
    TA --> OUT["Spoken answer<br/>and updated screen"]
    TB --> OUT

    classDef q fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef dec fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,color:#111827
    classDef ta fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef tb fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    class Q,OUT q
    class R dec
    class TA ta
    class TB tb
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1k1Fv2jAQx7_KKTzwElSSAOkQSkVUaZP2MJUy7WHZw8W-NFGCDbYzhtp-9x4BWspEnuz_-f73u3P87AktyZuCVzR6K0o0DpZppoC_h9-ZtyDlyIBdE9Y28_7AYJDA4jnzfpXooK6UnOXmJtEFGNq0ZN1d5r0e0hf7sy-Z1w_Tb9-hVZJ9RsO63yX0pdFrQLVzZaWeAHP9lyAa1_3Me4HlnCvP8mS5WxPMZzd50uUwBInShwKtgxVjN7yuGubrwrMq-Wr0BrRqdrObKmHaC5BtuQOuZ_kI3R05tvs-WHIlARpCaKqagx1GeoaR_ofRaF1Du2Yc4azfhQQ7FG1zghMliRpE5dBVWtkTJUppYa5cySOoxCfU5bwb8I-fSy79uNY1KR6S3R5bRCW5okRHEqwwROojMz1lZuqgiAatvacCNvspNdOezAkL8q0z7DvtheNJRPlxO9hW0pXTcP3PF7rRZtob5kEe4YWVJHE0ozHF79nT3iSPw9vhVbMgCG7D-MLM4QlMFILid69ggtEIr4ONQwoml1750augIhIfXvJLHA8nV71G4wCH0ZkXPPg8QticS4t92-cC35LDT0LKAJ4P3orMCiu5f0_8RvifWlHGm8yTVGDbOH4c-2PYOv24U4JDzrTEyuFW7yt8Mrg6yq9vyEYpPg) — zoom, pan and export</sub>

The router that picks between them is **pattern matching, not a model call** — see [AD-3] in §7.2.

### 2.5 Where the time goes

Budgets are p99: 99 turns out of 100 must come in under them. An average that meets the target is not a pass.

```mermaid
flowchart LR
    L0["<b>L0</b> · 300 ms<br/>your words appear<br/>as you speak"] --> L1["<b>L1</b> · 700 ms<br/>you finish, and a thinking<br/>indicator confirms it"]
    L1 --> L2["<b>L2</b> · 1.5 s<br/>first audio<br/><i>Type A</i>"]
    L2 --> L3["<b>L3</b> · 1.5 s<br/>first audio<br/><i>Type B</i>"]
    L3 --> L4["<b>L4</b> · 3 s<br/>shortlist on screen"]
    L4 --> L5["<b>L5</b> · 6 s<br/>explanation text<br/>and citations on screen"]

    classDef fast fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef mid fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef slow fill:#ffedd5,stroke:#ea580c,stroke-width:2px,color:#431407
    class L0,L1 fast
    class L2,L3,L4 mid
    class L5 slow
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNqV08uOmzAUBuBXOSJb0phbaBFCajVLVm13pYsTXwYrYCPbKIlG8-51gtuESLMoO__G37HN4S2imvGogkgM-kR7NA7a750C_7TkVxfVh6Yl9e7QQDcTcighIwRGWx_Mrrno2cBJG2YBp4mjuaVowU-A9cGxi37DdttAmwQqeaTKFQVCKmn7GFAxQHC9VEepXm_TUjFJ0WkDVCshzWhBOo-HjSZLkTQUSR-LJJ8KWGr4ddYBzkzq27iWzc_LxOFrvZPNHUsXLAtY9n_YtzWWLVgesHx1k4GyvTZukJ7TCiw1nKs7kC9AEYDiEdgHgJ-nARU66dc7fnbLZ_C3SKW7pfZJXmw6oLUvXIBAX1vIYag2jArKy9g6o4-82iR7zHIMw-1JMtdX6XSOqR60qTakSHmyf9JGyQImuMjoHWNfypLsP8TyIkGSPWHWd-VfTXDGin8ax-IzoR9rWZKT8kHz7Rz7RrmedZWmcZvF_pr9tld5casdxRCN3Iwo2fUneesi1_ORd37QRYwLnAffh-_X13B2-sdFUT_lzMx9Mk8MHX-R-GpwDPH7H8BAEq4) — zoom, pan and export</sub>

| # | Stage | Budget |
|---|---|---|
| **L0** | A word you say appears on screen, and the listening state is visible | **< 300 ms** |
| **L1** | You stop speaking, and the final line plus a thinking indicator confirm it | **< 700 ms** |
| **L2** | First audio out — Type A | **≤ 1.5 s** |
| **L3** | First audio out — Type B | **≤ 1.5 s** |
| **L4** | Shortlist drawn | **< 3 s** |
| **L5** | Explanation **text and citations drawn** (not audio finished) | **≤ 6 s** |
| **L6** | Booking confirmed: both calendar entries written, code shown | **< 5 s** |
| **L7** | Cancel or reschedule | **< 5 s** |
| **L8** | PDF emailed | **< 30 s** |

> **Why L1 is not smaller, and why L0 exists.**
>
> 1. **L0 — the live echo (< 300 ms).** Your words appear as you speak. No end-of-speech needed, so it costs nothing — this is the number held strict, and the one that makes the system feel instant.
> 2. **L1 — the nod (< 700 ms).** You stop; the final line and a thinking indicator confirm it. The clock starts at end of speech, and the system only knows you finished after 400 ms of silence (**P3**) — a floor under L1.
> 3. **Why L1 stays at 700 ms.** Shrinking that 400 ms does not buy speed; it cuts people off before the number or area name they were about to say. So the strictness goes to L0 instead.
> 4. **L2 — readback, Type A (≤ 1.5 s).** Requirement turns must wait for Job 1: the readback sentence *is* the fast model's output.
> 5. **L3 — answer, Type B (≤ 1.5 s).** Explanation turns do not wait for Job 2 at all — code builds the opening sentence from facts already resolved (**P8**, §9.5).
> 6. **Same budget, opposite reasons.** L2 uses a fast model on the path; L3 takes the model off the path. That is why L3's original 2.5 s no longer applies.

**How long the audio plays is never a target** — that depends on how much there is to say, not on how fast the system is.

**The nine conditions the budgets depend on** (spec §5.2). If any one of these is not true, the numbers above are void:

| | Condition | Where this document keeps it true |
|---|---|---|
| **P1** | The process stays awake — no sleeping, no serverless | §2.2, §13.6 |
| **P2** | Connections are reused, not reopened per request | §13.6 |
| **P3** | Deepgram declares end-of-speech after a 400 ms silence — and **no shorter** | §7.2 |
| **P3b** | A content-aware hold: a pause after *under*, *near*, *and* or a bare number is not the end of the sentence | §7.2 |
| **P4** | Speech synthesis starts on the **first sentence**, not the finished answer | §7.4, §9.5 |
| **P5** | OpenStreetMap facts are precomputed | §3, §8.3 |
| **P6** | The two calendar writes go out at the same time | §10.2 |
| **P7** | The careful model's thinking effort is set explicitly | §13.5 |
| **P8** | On a "why?" turn, the first sentence spoken is built by code from facts already in hand — first audio never waits on Job 2 | §9.5 |

### 2.6 How the rest of this document is organised

It follows the order in which the work actually happens — from the data gathered before anyone speaks, through a live conversation, to running and testing the thing.

| # | Section | What it covers |
|---|---|---|
| 1 | **§3 · Before anyone speaks** | The offline build pipeline: importing listings, curating them down to ten per area, reporting which fields the source actually carries, indexing the neighbourhood documents, and precomputing every map fact. Everything the system can ever say is collected here. |
| 2 | **§4 · How a single fact is carried** | The wrapper that every fact travels in — value, source, method, freshness, citation. The smallest structure in the design and the one that makes "say where it came from" impossible to forget. |
| 3 | **§5 · What is stored** | Everything the system knows about — areas, flats, map facts, guide chunks, the renter's requirements, bookings, the build record — grouped by how long each one lives, and the deliberate absence of any database, transcript store or PDF store. |
| 4 | **§6 · The backend, part by part** | The three paths through the backend — the conversation, booking, and the support layer beneath both — and the full list of components with the one job each of them has. |
| 5 | **§7 · Listening and understanding** | Turning speech into text and text into requirements: the turn state machine, the 700 ms acknowledgement, how interrupting works, what the system remembers between sentences, and a Type A turn walked end to end. |
| 6 | **§8 · Choosing the listings** | How requirements accumulate without disturbing what was already agreed, why filtering returns three groups instead of one list, how distances keep their method label, and the one listing fact that can change at runtime. |
| 7 | **§9 · Explaining, with sources** | The four stages behind every "why this one?" — area-partitioned retrieval, one resolver per kind of claim, the careful model phrasing facts it was handed, and the assembler that drops any sentence it cannot cite. |
| 8 | **§10 · Booking, cancelling, rescheduling** | The states a booking moves through, the four mechanisms that keep it correct (confirm-time re-check, parallel writes, explicit IST arithmetic, the code as the only credential), and what happens on confirmation. |
| 9 | **§11 · What the renter sees** | The frontend, which works nothing out for itself: it draws finished view-models. Also the card rules, the three audio behaviours the browser forces on the design, and the small set of messages that cross the wire between the two hosts, and the **voice agent persona** — who the renter hears, and the rules that keep her in bounds. |
| 10 | **§12 · When something goes wrong** | The five shapes a turn can end in and why an empty result and a failure can never be confused, what still works when each provider is down, and why the system refuses to start rather than fail mid-sentence. |
| 11 | **§13 · Running it** | The complete tech stack; deploying two hosts without skew; measuring each turn so a missed budget is diagnosable; keeping imported text from issuing instructions; where the keys live. |
| 12 | **§14 · Proving it works** | The three test suites, what each one proves, why the harness skips real audio, and where determinism comes from. |
| 13 | **§15 · The decisions** | The eleven design decisions, each with the alternative that was rejected and the reason. |
| 14 | **§16 · What is left open** | The four things this document cannot settle yet — chiefly that neither the import nor the latency measurement has happened. |
| 15 | **§17 · Appendix** | The four rules taken from the specification, the seven principles this architecture adds on top of them, and a one-page index of the guardrails that hold them — G1–G15, each with the place in the system that enforces it. |

Reading in order works, but each section stands on its own; **§4 is the one worth reading first** if you only read one, because almost everything else leans on it.

---

## 3. Before anyone speaks — the build pipeline

Everything the system can ever say is collected **before the demo starts**. Nothing is fetched while a renter is waiting. This is one decision, and it buys three things at once: speed (no network hop inside a turn), reproducibility (the same files produce the same answers), and safety (a source site going down cannot take the demo down).

```mermaid
flowchart LR
    S1["<b>1. Import</b><br/>Bangalore_Properties_List.xlsx<br/><i>no owner names or<br/>phone numbers in this source</i>"] --> S2["<b>2. Curate</b><br/>keep up to 10 per area<br/>by a written rule<br/><i>never pad a thin area</i>"]
    S2 --> S3["<b>3. Gap report</b><br/>which fields the source<br/>actually publishes"]
    S3 --> S4["<b>4. Build the guide index</b><br/>1 to 3 guides per area,<br/>split semantically into chunks,<br/>embedded into ChromaDB"]
    S4 --> S5["<b>5. Precompute maps</b><br/>run the fixed OpenStreetMap<br/>question set for every listing"]
    S5 --> S6["<b>6. Manifest</b><br/>counts, gaps, curation rule,<br/>question set, embedding model,<br/>index date"]
    S6 --> OUT[("Artefact bundle<br/><i>read-only files</i>")]

    classDef step fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    classDef out fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    class S1,S2,S3,S4,S5,S6 step
    class OUT out
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1k8tu2zAQRX9loGxaQFZiy3ZQwzDQxEA3DVJU7SrqgiJHFhGKZPmobQT5945E1w5aVDtxhvfcefAl40ZgtoKsVWbPO-YCfP5aa6Cvmj7V2brZTAuouGMW19fNZt24602DesdUdLFwqMN4tJYbH5y0YPYaHWjWowemxRi0ndEIOvYNOg8dOpKSmzr7AZPJBqpZ4swKuI-OhQvnGdFCtBAMTG_Aki5zyJKFIzDYOxkCanBR4R8XGn9RnmWC4qGTOl1JuFNds4QtE7Ys4BOz4NAaF87ofSd5B61EJTzpIHgTHU8UxkNkSh3BxkZJ36G_aJdJe5605wXcRanEqLCLUiBILfBwxkyH2soU8ucK8zHmrZIBPPZMB8lHoNSUzruon33KQWqpEChS5L5zpmfbu4udebKzSHYWBXxxyE1vY0DomfVnIy7q0WQrD6T2aFFXwSGGB2bH-M-IPkijyU-A1jgY2nwEKj9IvbsAFwm4TMBlAQ9My5bunkncRB18DjvC58CHiQ-6wwzzf1A5pAqJAT1tqkopYxNB0K5cyMuR_Pj929O7OvvoArY0J2iiFpfloN6KidHUyVYq9Gkt3pNC0uCKeb_FFnygxaMUtbpCgR9azGm5zTOurm55yVCcfid7KUK3mtlDzo0ybnU1w-nNcvGXmonhJCZ4y_H2LDZdsnLO_it2syC55RsxepJ5NcurMq_mebXIqebB6dsMqn_gZTlkPbqeSTE87pc6o-H21K0V1Jmg1kQV6ux1SGMxmOqoOYWCi0gn0Q6d3Uq2c6w_Hb_-BnmaXMU) — zoom, pan and export</sub>

**Three rules the pipeline enforces, because nothing downstream can fix them later:**

| Rule | Why it lives here |
|---|---|
| Personal data is removed **before** anything is written to disk | If an owner's phone number never enters the bundle, it cannot leak into the screen, the logs or a transcript later (spec §3.2) |
| Every listing gets a row for **every** OpenStreetMap question, `null` where there was no answer | Coverage is then uniform by construction. "No metro nearby" and "we never asked" stop being indistinguishable |
| Each document chunk carries its area, its title and its URL | Citations become possible at all, and the area tag becomes the retrieval partition key (§9.2) |

**Step 4 in three words, kept deliberately apart.** They are not the same thing, and the document uses them precisely:

| Term | What it is | When it exists |
|---|---|---|
| **RAG** | *Retrieval-augmented generation* — **the technique.** The model is never asked what it knows about an area; passages are looked up first, and the model is asked only to phrase those. It is a way of working, not a thing on disk | A behaviour of the system, visible in §9 |
| **Guide index** | **The searchable store** built by step 4, holding every chunk of every area guide | Built here, offline. Loaded read-only at start-up |
| **Guide chunk** | **One piece of one guide document** — a few paragraphs, carrying its area, title and source link. Splitting the guides is what creates them | Created here at build time. Every chunk sits in the index **whether or not any question ever retrieves it** |

---

## 4. How a single fact is carried

This is the smallest structure in the design and the one that does the most work. **Every fact that can reach a renter is wrapped in it.**

```
Fact<T>                      // in code: Provenanced<T>
  value        T or null     // "not stated" is a real value, not a blank
  source       DATASET | OSM | GUIDE | COMPUTED | NONE
  method       null | ROUTED | STRAIGHT_LINE   // required for any distance or duration
  timing       PRECOMPUTED | LIVE              // worked out earlier, or just now
  as_of        date or null                    // the index date, when precomputed
  citation_ref id or null                      // resolves to an entry in Sources
```

### 4.1 Why a wrapper instead of a number with a label beside it

A distance shown without saying *by route* or *straight line* is an automatic failure, and a distance where the **spoken words and the on-screen badge disagree** is worse than either mistake alone (spec §2.3, §7.2).

If the number and its label are two separate fields, keeping them in step is a matter of discipline — and discipline fails eventually, usually in the one code path nobody reread. Wrapped together, **a renderer cannot physically reach the number without going through the object that carries the method.** The mistake becomes impossible to make rather than merely discouraged.

```mermaid
flowchart LR
    F["Fact&lt;Distance&gt;<br/>value: 1.2 km<br/>method: STRAIGHT_LINE<br/>timing: LIVE"] --> R{"one formatter"}
    R --> V["<b>Spoken</b><br/>'about 1.2 kilometres<br/>in a straight line —<br/>the road distance<br/>will be longer'"]
    R --> C["<b>Card badge</b><br/>straight-line"]
    R --> L["<b>Full label</b><br/>Straight-line from<br/>coordinates,<br/>computed now"]

    classDef fact fill:#cffafe,stroke:#0891b2,stroke-width:2px,color:#083344
    classDef fmt fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,color:#111827
    classDef view fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    class F fact
    class R fmt
    class V,C,L view
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1ktFv2jAQxv-VUyq1L2ElgQJLEdIEZUOK9gAVL8s0XexzYtWxkeOUTVX_9zkJRQipect3vt_3-XxvATOcggQCocyRlWgdpNtMg__Wv7JgjczdKve4krVDzei2cI_z3N4vXlE1lED0JYaXqlMqcqXhCeyet9823388_0k3P5-6ipOV1EUC6Wb_lAW_YTBYwPYtC4wmEMZW6BzZLHjvbbddfe_N5_lidzAvpOf3-aIj3WFuGte7SmW8paW6q0gNCLWzKIvSgZIenTXxMBr3CUoCa5ADP92jU49SKcgJlNEF2Tsf7TLBsk-wRMshR17QOcWHzaC1uepK-65149EKc1Lnrt1lFwhr-rExYyyXGh3V4UmoDo0jDtocO3iPZwrrekUChH8SED56csOEQEGhz-OnlNwMZ1-jPD79Do6SuzKJD39DZpSxbXk0Go-vadUHjB5oSvkZNsmn8Wz4KSyKolk8vYK9SjqeaJwJRtMzLZrgaIyfR3uIKZpc0GDd3fNS2bZZL4V9uAzTzjMIIajIL5Lk7Sr71fIPXvmnSSALOAlslPP71R7DxpndP818ydmGvNIcuB_-SmJhsTrJ7_8B_v0AXg) — zoom, pan and export</sub>

**The rendering rule.** One formatter takes the wrapper and returns *all three* renderings from the *same* object. The grounding test suite checks three views of one truth, not three independent pieces of code that happen to agree today.

`null` lives inside the wrapper too, so "not stated for this listing" travels with its reason instead of degrading into a blank cell or, far worse, a zero. A missing deposit is not a deposit of ₹0.

---

## 5. What is stored

### 5.1 The things the system knows about, and how they connect

The colours group them by **how long each one lives** — which is the single most important thing about them.

```mermaid
flowchart TB
    subgraph BUILT["Built once, before the demo — read-only files"]
        direction TB
        LOC["<b>Area</b><br/><i>a part of Bengaluru:<br/>Indiranagar, Koramangala…</i>"]
        FLAT["<b>Flat</b><br/><i>rent, deposit, bedrooms,<br/>floor, parking, where it is</i>"]
        MAPF["<b>Map fact</b><br/><i>nearest metro, bus stop,<br/>shops — measured in advance</i>"]
        GUIDE["<b>Area guide</b><br/><i>a Wikipedia or city-guide<br/>page about that area</i>"]
        PASS["<b>Guide chunk</b><br/><i>a short piece of a guide,<br/>kept with its title and link</i>"]
        REC["<b>Build record</b><br/><i>how many flats were found,<br/>which details the site did not<br/>publish, and when it was collected</i>"]
    end

    subgraph LIVE["Alive only while the renter is talking — nothing is saved"]
        direction TB
        WANT["<b>What the renter asked for</b><br/><i>budget, bedrooms, must-haves,<br/>where they commute to</i>"]
        SHORT["<b>Current shortlist</b><br/><i>the flats being discussed<br/>right now, in order</i>"]
    end

    subgraph KEEP["Outlives the conversation"]
        direction TB
        BOOK["<b>Visit booking</b><br/><i>which flat, which hour —<br/>stored in Google Calendar,<br/>not here</i>"]
        CODE["<b>6-character code</b><br/><i>the only way back<br/>to a booking</i>"]
    end

    LOC -->|"has up to 10"| FLAT
    LOC -->|"has 1 to 3"| GUIDE
    GUIDE -->|"is cut into many"| PASS
    FLAT -->|"has one answer for every<br/>map question we ask"| MAPF
    REC -.->|"counts and describes<br/>everything above"| LOC

    WANT -->|"narrows down to"| SHORT
    SHORT -->|"points at"| FLAT
    BOOK -->|"is for one"| FLAT
    CODE -->|"opens"| BOOK

    classDef built fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    classDef record fill:#f5f3ff,stroke:#7c3aed,stroke-width:1px,color:#2e1065
    classDef live fill:#cffafe,stroke:#0891b2,stroke-width:2px,color:#083344
    classDef keep fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    class LOC,FLAT,MAPF,GUIDE,PASS built
    class REC record
    class WANT,SHORT live
    class BOOK,CODE keep
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNqNVttu20gM_RVCeZU3cZykrREYcK4bJF0HTdo8rPdhpKGsgaUZ7VziGm3_fUmNnMpOu62eJA3FQ55zSPtLkhuJyRiSojKrvBTWw-PZXANdLmQLK5oSzj7e3D3-PU_Ogqo8GJ1jChkWxiL4EkFibWAeDg-GR2BRyIHR1RoKVaGbJ__EXHxJZTH3yugXBL7uZueU-jSbTOnb0_1scprZ_cmpmghouBpTwBnqhaiCDeP27EZTJqHFQtgUbo0VteBzwSUcnpzuq8kW7NXd9DEiXFXC9xEsap9S-Y1xynNL0hpTu7Q9Jz4M5acalkovUliVSP0qD8q9gng_vb-KEO9FA4XIt2A0CovOQ43eGoIJDpw3TYRxpWnchr0ahQsWJSgNQj4LYvoV1vXHm4vL74zBIiiJ27w9qaVqUCoBxkKu_HoQgzigEQsEkZngSTvhQbSs72DcTx8eIsQ1fwh5GfRyG4PqJnEahTmyRF0dsaclNh5WypdElwOvfEWQWkKlOMsO1ofLTn92lyQD5cbKPlZpVkAKk6NIPgcrlqEwQcsItipVXpKIXqjKtX4kMcmUSoI2PvYcskq5Mm2LIB01y7gSDnJTVWRJlFtVoZZzvTMCdzefmPRppZ6pX_Y34VbR_2wjtOQL8KJis2zkJPySH-nEiWeUvzENT9O_OrM-sTq99MItyRg0dH1usiAX2Lcu1MH5QUlobkMPxjFdU7d1HYgab16J8PDn7EOHex4sI0aBibYtK3M9UYYMuTOpXB6cIwI5wKpF6anrVcoGJhnR_pLY28vLewKeBc_URgFzo5_ROsHs_AZnZ7PZbaz9kyLtITOGVejXHU3ClfMg831pgu10inPoTTd418YsSNlzUVG9tGLaY5ISmMlXzJ3PNtN4MuD1SbNPYvFS3eUtukasIRP5sj3whubmpdofE0XrEQaDydd5UpJhQ0PqwfBgnnxt99qPYoYcMuKIdlXEkPa2CyI75jT-SlMcDxaH8sTHSE7by2Y0z66jqWPvAZIw67b4mjbdv4H2GsuxQvYnJ-JVGBPRYMPgjzZRTuNKnuHxk-hyqzJ0bZI2XRwS2knPyBmom03zPA1dLVpYa1YOpFlpapADW9PGwPa2i2yMasH8Nknsku8EcC_U2nYIa9mFmAa141P-bFNOXgnnLrCgFc4_hPQLV433UOK7AlNHu32J4703-Uig7B4HKyV9OT5sPqe0aowd7x3i8ODkeCdd3HldvuK4GBXF_-Yb_iJfu6RitrwoRK-6g7fvhtnhT6s7eDsaHR3tZFsiNl02mRc5vnnJNjwRoyPx82zHVN1JLxtLmzLdKbskbT2ZsvMiof1INk-kpf-W_ZBGrbnH_hHrlLYCcr1JCkmNthZK8n-bL_OEJrAmuccwTyQWIhBc8o3DRPDmYa1zOvI20D-bJDRSeLxQgjZU3b3-9h_DGfCz) — zoom, pan and export</sub>

| Colour | Lifetime | Why it matters |
|---|---|---|
| 🟪 Purple | **Built before the demo, then never changed** | Nothing here is fetched while a renter waits, so nothing here can be slow or unavailable. One field is shadowed at runtime — availability, by an in-memory overlay (§8.4) — but the files themselves never change |
| 🟦 Cyan | **Exists only during one conversation** | A refresh loses it, a second tab starts a fresh one, and nothing is written to disk |
| 🟩 Green | **Survives the conversation** | And it survives in *Google Calendar*, not in a database of ours — the code is the way back to it |

**How to read the arrows:** an arrow means "leads to" or "is made up of". *An area has up to 10 flats. Each flat has one answer for every map question we ask. An area has one to three guides, and each guide is cut into many short chunks.*

### 5.1.1 The same things, in engineering terms

| Plain name | In code | What it holds | The point to remember |
|---|---|---|---|
| **Flat** | `Listing` | The 18 details from spec §3.1, **each one a wrapped fact** (§4) that knows it came from the dataset, plus an id, its area (the specification's `locality` field), and a note of any duplicate merged into it | Two adverts for the same flat are merged when the address matches or the coordinates are within 50 m |
| **Map fact** | `OsmFact` | One row of *{flat, question, answer}* — always from OpenStreetMap, always measured in advance, always stamped with the date | The question comes from a **fixed list**, so every flat has a row for every question — `null` where there was no answer. "No metro nearby" and "we never asked" stay distinguishable |
| **Guide chunk** | `GuideChunk` | A short piece of an area guide, with its area, title, link and the date it was fetched. Created by splitting the guides at build time — it sits in the guide index whether or not any question retrieves it | The area is not a label on the passage — it is the **key the whole index is split by**, which is what stops one area's text being quoted about another (§9.2) |
| **What the renter asked for** | `ConstraintSet` | Firm requirements, softer preferences, the commute point, and a flag per item saying whether it has been read back and confirmed | **Never edited in place.** Every change makes a new one, which is how "you changed only what I asked" can be proved (§8.1) |
| **Current shortlist** | `Shortlist` | The flats being discussed, in a fixed order, in three groups: matched, unknown-on-a-detail, and excluded-with-a-reason | Grouping the cards by area on screen must never reorder it (§8.2) |
| **Visit booking** | `Booking` | The flat, the hour (in IST), the state it is in, both calendar entry ids, and the renter's email | The states it moves through are in §10.1 |
| **6-character code** | `ConfirmationCode` | Nothing but the code itself | It is the only credential in the system. Unknown codes and cancelled codes get **identical** answers, so it cannot be used to discover other people's bookings (§10.2) |
| **Build record** | `DatasetManifest` | Every area with its count of flats and the total, the availability marker found, the list of details the site did not publish, the rule used to trim over-supplied areas, the map question list, **the exact embedding model and version used to build the guide index**, and the date | This is exactly what sign-off requires published (spec §7.3). Producing it **as an output of the build** rather than writing it by hand afterwards is **[AD-2]** |

### 5.2 What is deliberately not stored

**No listings database. No transcript store. No PDF store. No user table.**

```mermaid
flowchart LR
    A["Personal data"] -->|"removed at import time"| A2["never enters<br/>the bundle"]
    B["Conversation"] -->|"in memory, expires"| B2["gone when the<br/>session ends"]
    C["PDF"] -->|"emailed"| C2["nothing retained"]
    D["Booking"] -->|"written to"| D2["Google Calendar<br/><i>the record of truth</i>"]

    classDef gone fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    classDef kept fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef src fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,color:#111827
    class A,B,C,D src
    class A2,B2,C2 gone
    class D2 kept
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1kk1v4jAQhv_KyL0GFbwFqgghQaLdyx5Wu7fd9GDiSWLheCLblFZt__uOUwS0UnPKfLzPfHheRE0aRQ6isXSsO-Uj_PxdOeBv868Sv9AHcsqCVlFV4gEmk_VrJTz29IgaVIRQezUgRNNjJV5hI1nl8BE9oIusXu387Tp2CLuD05ZzHt7pW84ryHFiUNGQu8CNg575_jkDfBqMx5DA2wRuySEcO3TAxJEcMARWczEdzuwidV5-vyCxV8aiTpxibJBiZ1wLHqMyLgVOypKDW6I9By_qozcxppqUAGUC_CBqLUKhLBdWfmxlZcY5PdbkNVAD0R9it7o16xH_XqC2KoQSGxhHaYy1-U2DKFFmIXraY36ja7mQi5M5ORodu1wOT1lNlnx-czefqqn6RNvjEE80XTc1Ls-02UJ9u1Nf0qZzibPFJ1rw9QmGc1zi7gxb7JbyfvolbDab3cvlFQw22TYrsjIRP7hltpVZIcctXAdKOY4iMhCtN5oPk5eIbPXo-Q2TQ7wkQSV41-nkcv7lF9hXonJvSTco95eov0g9HdqOzUbZkOzDwMeMpVGtV1dp6hDpz7OrT563_0bBAlM) — zoom, pan and export</sub>

**The absence of storage is a feature, and it should be defended.** Adding a database later would reopen every retention question the specification deliberately closed (spec §2.5, §3.2, §5.3). The one thing that genuinely needs to outlive a session — a confirmed booking — already lives in Google Calendar, and the 6-character code is how a renter reaches it again.

---

## 6. The backend, part by part

It is one process, but it is easier to understand as **three separate paths** that barely touch each other: the conversation path, the booking path, and the support layer underneath both.

### 6.1 The conversation path — follow the numbers

This is what happens between the renter speaking and the renter hearing an answer. **Every turn walks lane A. Only "why?" questions also walk lane B.**

```mermaid
flowchart LR
    MIC(["Browser<br/>microphone"]) -->|"1 · audio"| WS["WebSocket gateway"]
    WS -->|"2"| TO["<b>Turn Orchestrator</b><br/><i>runs the turn and<br/>picks the lane</i>"]
    STT["Speech to text<br/><i>Deepgram</i>"]
    TO <-->|"3 · words"| STT
    SM["Session Manager<br/><i>what has been<br/>said so far</i>"]
    TO <-->|"remembers"| SM

    subgraph LANEA["Lane A — understand, then choose  ·  every turn"]
        direction LR
        J1["Job 1<br/><i>Groq</i><br/>words to requirements"] --> CR["Constraint<br/>Reducer"] --> SE["Shortlist<br/>Engine"] --> CS["Commute<br/>Service"]
    end

    subgraph LANEB["Lane B — explain, with sources  ·  'why?' turns only"]
        direction LR
        RS["Retrieval<br/><i>this area only</i>"] --> RES["Resolvers<br/><i>one source per claim</i>"] --> J2["Job 2<br/><i>Anthropic</i><br/>phrases the facts"] --> CA["Claim Assembler<br/><i>drops the uncitable</i>"]
    end

    TO -->|"4 · always"| LANEA
    TO -->|"5 · only for<br/>'why?' questions"| LANEB

    LANEA -->|"6"| VM
    LANEB -->|"6"| VM
    VM["<b>View-Model Builder</b><br/><i>the only thing the<br/>browser ever receives</i>"]
    VM -->|"7 · first sentence"| TTS["Text to speech<br/><i>Smallest.ai</i>"]
    TTS --> EAR(["Browser<br/>speaker"])
    VM -->|"7 · cards and citations"| EYE(["Browser<br/>screen"])

    classDef user fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef core fill:#cffafe,stroke:#0891b2,stroke-width:3px,color:#083344
    classDef model fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef code fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef out fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#4c0519
    class MIC,EAR,EYE user
    class WS,TO,SM core
    class STT,J1,J2,TTS model
    class CR,SE,CS,RS,RES,CA code
    class VM out
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNqNVW1P4zgQ_iuj8GFvpXA0bSlQVT21pTodoofUVKDTdj84zoRYJHaxHQra3f9-YycpgV2kjfqlHs8zzzzz4m8BVykGYwiyQu15zrSF6_VWAn2rfxZ_fNkGc632BvUk0SfTUnCtdrmSuA2-fobj4-n3bRDBtur1kjNgVSrUNvgOdzH53WESK_6AFu6ZxT17IZca-C5uPPvu8uaGLk-S6abSEm40z9FYzazSk5Nk6qNOxFRX0oDNEay7xWTqDTvBH-rjgkmcnIjpIUa82RBsvEPkOVgFFp9tC3aJuLvXrHzjsLmBSc1q0OazVzo1jiKBNagrB4rGCCVhxSS7b4Qh1H3OLOTMQIIo_aFhIgWjIGP6g1AaSywT1HWU1VbWF0yVEL9dDtezf5czCnlN6cGMePV70RAqmZKLJRVCl7wEnitlEFregE-oX7xUh5juS4VGbh31tsTuu4oowJVKIGoz-VurR0fY__ciOAU1PlbCEZaW6H51JYTFmnwXSrqKCVkLvMa04qjbK_HSSZYrbQth6htLeS98B9UYsccoy8qiN8eonwTHA3WU6S-FmbfCzFth8HlXEI8Q9sLmpHylOZpXWT7t85e_PnldDChZvPyGOmvHbo1WC3xiRauQzYUBppF5mKa4Ppv1snYwqqAimNaBJqbhAzvUwIlm2XW76jdF6LceM2lzmjXBD5XY5ZoZrPs9Y7xTBdciCwcJM2OooYrXrkwJo3apJBeWke1NL3bEpbasu3J4GOiCxtb3pm_Ed9dO22tOA8hUHbMR-bGiMSYxD97zNoyHaiBGznq7ejXMf2W4XdUb4lbg_nhF-6qAeSUKGoLuinA5eiZUHHnvUvaWpF5ffiaohzmKJzRvJLhdNUHP2oQyQeMFhjodpWtEWlIbV9YNLRE3CsavlTZwXLKioGz_ZOLtmG_8noPlbP1-jxIAe_Az8vkjDpy5uaMZB1e2g5TL_5Y_gXFNG6fGqtGovYy5xAwql3kmimJ8lCbIMgxpUtUDjo_6p6MBJs3f471IbT7u755Drgqlx0e9JEoG7B0aVxobNJ5lXbTe-UWU9N-iDTpo54PBcPgOrfSFrOEyzAb87ACXXpyd9UYfkhueRqw3-Ilc2pJLecbxFS0ascGQfZzqaR-j0Ts0VdmWWoZDHB3AMIrS4fnH1HjvNLrogLlXNKQOCKlwvhxd210cbm7CeOWV7RrowQmvovCqH7om8kp1zYt1GC_DRRyu6beMw8XMp9-9Qg1FOQQhBCXqkh4i98Z_2wY0FiV19Bi2QYoZqwq7DX64a6yyKn6RnExWV0gn1S6lh_tSMPdWNsc__gcL55qA) — zoom, pan and export</sub>

| Colour | Means |
|---|---|
| 🟦 Blue | The renter's browser — the only thing outside the backend |
| 🟦 Cyan | The parts that run the conversation itself |
| 🟨 Amber | **A call to an outside provider.** There are only four, and only two of them are models |
| 🟩 Green | **Plain code. No model, no network.** Every decision about listings lives here |
| 🟥 Pink | The single exit point. Nothing reaches the browser except through it |

**Three things this picture is meant to make obvious:**

1. **The orchestrator is the only part that knows the whole turn.** Everything else does one job and hands the result back. Nothing calls anything on its own initiative.
2. **Lane A is almost entirely green.** The only model in it turns words into requirements; the choosing of listings is ordinary, testable code.
3. **Both lanes end at the same box.** The screen, the spoken answer and the Sources list are built from one object, which is why the commute method cannot say "by route" in speech and "straight-line" on the card (§4).

### 6.2 The booking path — the same code whether it starts by voice or by click

A visit can be booked by saying *"book the second one, Tuesday at four"* — the orchestrator then calls the Booking Service — or, for cancel and reschedule, by entering a code on the confirmation panel. Either way the booking action itself is an **ordinary HTTP call into plain code**, never part of the audio stream. That is why a confirmed booking survives a refresh, and why cancelling needs nothing but the code.

```mermaid
flowchart LR
    B(["Orchestrator, for a spoken request<br/>— or the browser, with a code"]) --> API["HTTP API"]
    API --> BS["<b>Booking Service</b><br/><i>slot arithmetic in IST,<br/>plain code</i>"]
    BS -->|"still on the market?"| AV["Availability Register<br/><i>in-memory overlay</i>"]
    BS --> CAL["Calendar adapter"] --> G[("Google Calendar<br/><i>tenant + owner</i>")]
    BS --> PDF["PDF and mail"] --> GM[("Gmail")]

    classDef user fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef code fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef out fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#4c0519
    classDef ext fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    class B user
    class API,BS,CAL,AV code
    class PDF out
    class G,GM ext
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1k21v2jAQx7_KybxptSAIj2uEmEjRWKVWQwX1TbMXl-QCFk7MHAeK2n73XcLDGBp5Edn3P__-Z5_9LiIdk_BAJEpvoyUaC4_PQQb8-TevgfhpoiXl1qDVxoFEG0DI13pFGRj6XbA0CE1jGBStptsBlu2SIDR6mxPnb6Vd8oLSIxC_bqFeH8Jo-sDcH_P5tBxyeO_G40r2Z6wOwqGv9UpmC5iR2ciIBo1wWDkN5DBX2gIaZqdkZQQyg4fZ3KnktUKeloaDhhye6P6shH8EIrdSKdBZVWeKZkX2WyA-YPTCtqMNSoWhVNLu4JkWMrdkjq4yq6eUarMDvSGjcPcfA7gfPTLnHhVlMfJZxbhmBGdV6uT1JhATrReK4JhzxFvKMLPwBfQ2Y9OKffsvfDr-znD-A2YxFy_VCfxUkfehctV-XaQwz8eUQMHdgIR37tXikDAhh1vKTfRqrW6vTeFhWt_K2C691vrNibTSxqs1Qzds4wWtPN0jLUoi6p9obg_bHbxO67bI7V3QdGEPsCShDvVOMHLduPP1KqwTNbvu3QWM3k4wStrR38riu36_2bsO67rYbJ_BwK8O7TzCN9TxZw632Bm97O_0mVq2hbdyHpo4k6eyIuGASMlwd-Lypb0Hgi9fyi_Cg0DElGChbCA-yzQsrJ7tsoglawriSLGO0dJY4sJgegh__gFqmjAC) — zoom, pan and export</sub>

No model appears anywhere on this path. Details are in §10.

### 6.3 Underneath both — the support layer

These parts touch everything, which is exactly why they are drawn once here instead of as a web of lines across the diagram above.

```mermaid
flowchart LR
    CFG["Config and boot check"] -->|"refuses to start<br/>if anything is missing"| AR[("<b>Artefact store</b><br/>dataset · guide index ·<br/>precomputed map facts")]
    AR -->|"read-only, loaded once"| USE["Shortlist Engine<br/>Commute Service<br/>Retrieval"]
    TEL["Telemetry"] -.->|"one trace per turn,<br/>one span per component"| ALL["every component above"]

    classDef plat fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,color:#111827
    classDef store fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    classDef code fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    class CFG,TEL,ALL plat
    class AR store
    class USE code
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1kk1v4jAQhv_KyFxaKWyBLqSLEBKi7F44QXuqe3DsCbHq2JHt0KK2_30nhmVRpeYUvzPzzOc7k04hmwIrjXuVlfAR1htugb7l7z9PnC2dLfUOhFVQOBdBVihfOHuGfn_-wZnHsg0YIDoIkaJnhb-Z65L8D7HSdgc6QK1DoF_OPmCxebribFbMFz5iKWSkKOdxdlPMU6QSUQSMwNvBoMhh12qFoK3Ct5OUvBqP0tVNG1FBLRroQIGz6-dj4YvNuTih-s6aQwbGCUXezkrs6njcrqi3beV8NDpEWNmdtpjgS1fXRIYt-r2WR22D0WvcC0ONH3M8rNYEeECDNdkOaSA_UlJnEaIXEqFBD7H1NkuMTg-NsEnuyifBxjSUdcfCPfrDfwOIwu0x5TtmlEaEcI8lNEZEKLUx0x6OMcciC9G7F5z2JkU-uhucnv1XrWI1HTVvmXTG-WlvOBzejfIvtDT_fziFv0o843J5K1B9ixvhcDAZf8F153SiKVlKzM-04UTc_hTf0gZj4k0uaN39ZTTmjMaTer600YpT4Zca7TSlZxmwGn0ttOoO-52zWNGWOD04U3R1raGxf3Zuoo1ue7CSTNG3SErb0AnivRY7L-qT_PkXY1QMIg) — zoom, pan and export</sub>

The artefact store is **read-only at runtime**, written only by the offline build (§3).

### 6.4 The full list of parts

| Group | Who is in it | Its one job | Where |
|---|---|---|---|
| **Edge** | WebSocket gateway, HTTP API | The only two doors into the backend | §6.1, §6.2 |
| **The conversation** | Turn Orchestrator, Session Manager | Knows what stage a turn is at, and what this renter has said so far | §7 |
| **Voice and models** | Deepgram, Groq, Smallest.ai, Anthropic clients | Thin wrappers over providers. They hold no rules of their own | §7, §9 |
| **Decisions** | Constraint Reducer, Shortlist Engine, Commute Service, Booking Service, **Availability Register** | Every question that has a right answer, plus the one listing fact that can change at runtime (§8.4) | §8, §10 |
| **Grounded answering** | Retrieval, Resolver Registry, Job 2, Claim Assembler | Fetch facts, phrase them, and throw away anything that cannot be cited | §9 |
| **Presentation** | View-Model Builder, PDF and mail | Turn facts into exactly what the screen and the PDF will show | §11 |
| **Platform** | Artefact store, Calendar adapter, Telemetry, Config and boot check | Hold the things everything else depends on | §6.3, §12.3, §13 |

---

## 7. Listening and understanding

### 7.1 The shape of a turn

One state machine per conversation. It is the only piece of code that knows what stage a turn is at.

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> CAPTURING: renter starts speaking
    CAPTURING --> TRANSCRIBING: end of speech detected
    TRANSCRIBING --> ACK: words on screen + indicator
    ACK --> CLASSIFYING: which kind of turn?
    CLASSIFYING --> TYPE_A: preference or refinement
    CLASSIFYING --> TYPE_B: explanation
    TYPE_A --> SPEAKING
    TYPE_B --> SPEAKING
    SPEAKING --> IDLE: finished
    TRANSCRIBING --> CAPTURING: renter interrupts
    ACK --> CAPTURING: renter interrupts
    CLASSIFYING --> CAPTURING: renter interrupts
    TYPE_A --> CAPTURING: renter interrupts
    TYPE_B --> CAPTURING: renter interrupts
    SPEAKING --> CAPTURING: renter interrupts

    classDef wait fill:#e5e7eb,stroke:#6b7280,color:#111827
    classDef listen fill:#dbeafe,stroke:#2563eb,color:#0b1b3a
    classDef work fill:#dcfce7,stroke:#16a34a,color:#052e16
    classDef talk fill:#fef3c7,stroke:#d97706,color:#451a03
    class IDLE wait
    class CAPTURING,TRANSCRIBING listen
    class ACK,CLASSIFYING,TYPE_A,TYPE_B work
    class SPEAKING talk
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNqNlF1vmzAUhv-KRe42IoXQQMfFJvKxKWpVRaG7qMo0GfvQWCE2ss2yqep_n8GEULq15QLB8fvY5z3H9qNDBAUnQo7SWMOS4QeJD-Nf05Qj89x_-IHG489ovbxe2Uj91YQW8eb2-3Z98y1CErgGicwMUiukSsB7xh-svpM10O02vkkW2_W84YBTJPIaALJDFDQQDdRyfWWDxourCB2FpAoJjhSRABx9RIxTRrAW0mJGZbO7jpNk_fWuWee4Y2Z-k1OznK4k_9Imd1bZ9O42q59xhEoJORhXBJCQxl7OOByMyVeoubHzuywwx5oJ3npopms0yWYVXxmgNzD_x8Dpryt6hMzaTO3-W5aXbWD1W1alVoOSvKkcGnub6Dl8p3j-TvGzSrwutwApsFJLyNERM22qVhTRCGYQQuYqLcUeolGQhdPLiUtEIWQ08jzvchoO4IIpbfaVxWkGOIcOn84C38zW4pPMy3w8XFvI_QkmOYGwg70A-xe4g2dT8IIBrHFxgnPIfXKG6acwnAQn-GLm4Ynfg-2hrH33g13R3GebxjrsC80GcXutd21T3bZdtaW-umtMna7jIucA8oAZre-Qx9TRO3NSUvOTOhRyXBU6dZ5qGa60SP5wYoa0rMBEqpKer5w2_PQX1zJmug) — zoom, pan and export</sub>

**The acknowledgement is the load-bearing state.** `ACK` fires the moment the final transcript is on screen and the thinking indicator is up — **before any model is called**. That ordering is the only reason the 700 ms budget is reachable at all; the specification says explicitly that no model call may sit inside L1.

**Interrupting works because every active state has an edge back to `CAPTURING`.** If the renter speaks at any point after the turn has begun, the machine returns to `CAPTURING`, cancelling the audio stream in flight and, if it is still running, the Job 2 call behind it (spec §6.17). Speaking over the *answer* is the obvious case; speaking over the *thinking* — after the acknowledgement, before the first word of audio — is the one that is easy to miss, and dropping it on the floor is worse than talking over the renter. What no edge does is skip the acknowledgement: `CAPTURING → TYPE_A` remains illegal, which is what keeps a model call out of the 700 ms budget.

### 7.2 Turning speech into text, then picking a lane

Speech goes to Deepgram over **one WebSocket that stays open** for the whole session — opening a new one per utterance would spend the L1 budget on a handshake. Deepgram is configured to declare end-of-speech after a **400 ms** silence (P3) — the single largest term inside L1, and deliberately no shorter: natural pauses before a number or an area name run roughly 200–500 ms, and a window inside that range cuts people off. On top of it sits a **content-aware hold** (P3b): if the words so far end in *under*, *near*, *with*, *and*, *to* or a bare number, the orchestrator waits up to 400 ms more before treating the silence as the end — plain pattern matching, with Deepgram's utterance-end event at about a second as the hard stop. It is primed with the name of **every area in the imported dataset**, generated from the dataset rather than typed by hand (spec §5.1).

**[AD-3] Choosing between Type A and Type B is pattern matching, not a model call.** Explanation-shaped requests — *why*, *what is the area like*, *is the commute realistic* — are matched against the current shortlist context before Job 1 runs. Asking a model which model to call would spend the acknowledgement budget twice, for a decision a short list of patterns gets right.

### 7.3 Remembering the conversation

An in-memory map, entries expiring on a timer, one lock per session. It holds:

| What it holds | Why it must |
|---|---|
| The current `ConstraintSet` | So each new instruction edits the whole picture, not just the last sentence |
| The current shortlist | So refinements can be applied to it |
| **The last order that was read aloud** | *"the second one"* must mean the second one the renter **heard**, not the second in whatever order the system now holds internally (spec §6.30) |
| The clarifying-question counter | The budget is 5 questions, and it is enforced here (spec §2.1) |
| Whether audio playback has been unlocked | Browsers block sound until the user clicks something (§11) |

Two behaviours fall out of this design rather than needing code of their own: **a second tab is a second conversation** (spec §6.22), and **a refresh loses the conversation** (spec §6.21). A confirmed booking survives either, because it lives in the calendar and is reachable by its code.

### 7.4 A Type A turn, step by step

```mermaid
sequenceDiagram
    autonumber
    participant T as Renter
    participant FE as Frontend
    participant TO as Orchestrator
    participant DG as Deepgram
    participant J1 as Job 1 (Groq)
    participant SE as Shortlist Engine
    participant TTS as Smallest.ai

    T->>FE: speaks
    FE->>TO: audio frames (streaming)
    TO->>DG: audio (connection already open)
    DG-->>TO: partial transcripts
    TO-->>FE: partial transcript on screen ⟵ L0 under 300 ms
    DG-->>TO: final transcript (400 ms silence, longer if the sentence looks unfinished — P3, P3b)
    rect rgba(34, 197, 94, 0.16)
    TO-->>FE: words + thinking indicator ⟵ L1 under 700 ms
    end
    TO->>J1: transcript + current requirements
    J1-->>TO: what changed, as structured data
    TO->>SE: apply the change, then filter (in process)
    SE-->>TO: matched / unknown / excluded
    rect rgba(234, 179, 8, 0.18)
    TO->>TTS: first sentence only ⟵ P4
    TTS-->>FE: audio starts ⟵ L2 under 1.5 s
    end
    TO-->>FE: shortlist ⟵ L4 under 3 s
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNptVE1v4jAQ_SujnKiasqTQpeXQEx8SWolqwzEXYw9gkYxTf6iLqv73HYeEZSmRIjme5_F7zy_-TKRRmEwgcfgekCROtdhZURUE_IjgDYVqg_b0XQvrtdS1IA9rEA5-I_lbxfksVufWcJnUjcWrWF9ZuUfnrfDmRo_pImKmiPU_Qpf1ZRbrS7OBDHoLa97vvmPyhke-N9aX2nmY0U4T3uCzzhtgJcqSGfWFLuiEWj-8vs5nE3A1ioM7zc1nPLleTdgfpQ1smR466LESFJWmXUtkvWLYdNHBetIQofTaEIiSoeoIpkZq0dPFQ9u1ISZKYGPISatr784NWzbfIcBdeYRIUITH8fYJfg0gkEILw8EAKne9y1bT_w16owYHTpcxCCmUhna8XG_B7xFcPGqe52lzcNyaG2i3RxX3G2QjeBum_G5aOZaVgt1tRG84SiF7GafwwoNBP_t5d63mw1jl4J630XRg_0CT0jKm4qwla7WML7Sck9UYvcwml2ruQQZrmTMzeQ_aYsXjduEy60z42AsPci9YqEpjAvgMg_TBsiwlvLjonzNRUdflsXHjtCaNY2IrS_4LoKcJamskOtdKzGfdRpXwMnr1g3UcyHwQj_CPLINCdW3YY-PY-CWF58aw58s8cVLj2VkO8_lEDDGr1qm3UQte5529p_g5z5lxZ0MfW0Oz_hPc8LNL_fnP6daNulCBS1JIKrSV0CreIJ9Fwm5UWPBHkSjcilD6IvmKsHiR5EeSSTyjwL4loWZ_u9umnf76C0v0cyY) — zoom, pan and export</sub>

Note what is **not** in this picture: no network call to a listing site, no map lookup, no second model. A Type A turn touches three providers — speech in, the fast model, speech out — and otherwise runs on data already in memory.

---

## 8. Choosing the listings

This whole section is plain code. No model participates in any decision here.

### 8.1 Applying what the renter just said

`(current requirements, one edit) → new requirements`

The fast model's job was only to say *what changed*. Applying that change is a function, and it changes **one field at a time**, leaving everything else exactly as it was. Changes accumulate: "under 40k", then "actually 35k", then "and a lift" is one set of requirements, not three separate searches (spec §2.2).

Requirements are **never modified in place** — each edit produces a new set. That immutability is what makes the edit-correctness suite meaningful: it can compare the before and after directly.

If a new limit contradicts an existing one, the reducer returns **a question, not a new set** (spec §6.5). Contradictions surface as something to ask about, never as a silently broken filter.

### 8.2 Filtering — three groups, not one list

```mermaid
flowchart TB
    IN["All listings<br/>+ the renter's requirements"] --> ENG{"Shortlist Engine<br/><i>a pure function</i>"}
    ENG --> M["<b>matched</b><br/>every hard requirement met"]
    ENG --> U["<b>unknown on</b><br/>a required field is<br/>'not stated' for this listing"]
    ENG --> X["<b>excluded</b><br/>failed a requirement —<br/><i>kept, with the reason</i>"]

    M --> S["Shortlist shown"]
    U --> O["Offered separately:<br/>'3 more where the deposit<br/>is not stated — want to see them?'"]
    X --> E["Powers the empty state:<br/>'nothing under 25k in Koramangala'<br/><i>not just 'no results'</i>"]

    classDef in fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef eng fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,color:#111827
    classDef good fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef warn fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef bad fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    class IN in
    class ENG eng
    class M,S good
    class U,O warn
    class X,E bad
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp9lFFvmzAUhf-KRR7yMKoCaZIORZk2tZqmqeukrFKlsocLvg5ewGa2GY2q_vddIKQ0U5cnuPb9zrkHx09epjl6MfNEoZssB-PYj0-JYvT78u0h8T4WBSukdVJt7So15-t3zOXIDCqHZmrp4XctDZb0bhPvJzs7W7Prb5-fEm-Ta-PaVnattlJh172Sa2BVbZCJWmVOarU6l-vEe-4lqbMj3JDyKl2X4LIc-eo8XXfd-AfNnpFJPtZlJTqSfk246wm12indKNbqHCAw9HImJBacyX6wqdKOWQcO-ZQJbWhOaYfZ_-Hf93x8zIqajywKkAWR4ZXBpI6C8GIIYIeV81kjXX6IEuwQA4n0MjedyOZhHKPNaZKjkbtuxy3tuBUC22ksVmDIfrGP-4FmrNSUdJPTcifFsdJWum6VZnsZ-OCQNUBunSZU11B-mB717vtPS3rfdYPGdkAsK7fvGfExxJzyYrXiaFg03zGp2FdtoAS1hQKmQwqt-K-axqIWysDWhbPTkxSyAqy9QtEyhCyKeMJTBIG-dUbvMJ5E88UM08PrWSO5y-OoevQzXWgTT4I0TGdwwkJy18NwjstjdzxZpMvoMngTFobhZbQ8gW215oO1TGS4PNLCBcwu4G1r8wjDxQmtATMMKlDMshcaf79cBos3aRfzEILZCS0FfoRhhNELLIsW0f9gAQTj1OgmoC8wLrT_AspxXLrxN10a49qdf9vNNK7d-9etM89nXommBMnb24fui_a8YUIvicdRAJ0HuhbabVA7vdmrjJacqZEqdcXpxF1J2NK5OpSf_wIn4I_Q) — zoom, pan and export</sub>

**Why three groups.** A listing whose deposit is simply not published has not failed the renter's budget test — but it has not passed it either. Dropping it silently would turn every sparsely-filled field into an invisible filter, quietly making results worse the more fields the schema has. So unknowns become their own group the renter can opt into (spec §3.1).

**Why rejects are kept.** Holding on to the *reason* each listing failed is what lets the empty state name the requirement that is actually binding, and suggest a relaxation. The system never relaxes anything by itself.

**Ranking is stable, and separate from grouping.** The cards are grouped by area on screen, but that grouping is presentation only — it must not reorder the shortlist. That separation is what lets the edit suite demand that untouched listings come back byte-identical, in the same order.

### 8.3 Distances and commute times

Two paths, and they are never mixed up, because the answer is a wrapped fact (§4) that must name its method.

| The question | How it is answered | What the wrapper says |
|---|---|---|
| "How far is the metro from this flat?" | Read the precomputed OpenStreetMap fact. **No network call.** | `source: OSM`, `method: ROUTED` (or `STRAIGHT_LINE` where routing failed at build time), `timing: PRECOMPUTED`, with the index date |
| "How far is it from my office in Whitefield?" | The destination is not known until the renter says it, so: **straight-line arithmetic over stored coordinates** — local maths, no network call | `source: COMPUTED`, `method: STRAIGHT_LINE`, `timing: LIVE` |

Real routing for the second case is an opt-in path, taken only if the latency budget proves it affordable.

**The service cannot return a distance without a method.** That is not a code review rule; it is the wrapper's shape. And every straight-line answer carries its caveat **in the same breath** — a straight-line figure heard as a travel time understates a Bengaluru commute badly enough to change someone's decision.

### 8.4 Availability — the one listing fact that can change after the build

Everything else in the dataset is frozen at build time. **Availability is not**: a flat can be taken off the market between the import and the demo, or between being offered and being confirmed. It is therefore the only listing field with a runtime owner.

| Where it acts | What happens |
|---|---|
| **Filtering** (§8.2) | An unavailable flat is `excluded`, with "no longer available" as its reason — so the empty state can say *why*, and it never silently vanishes |
| **Admin toggle** | A small endpoint flips the flag for one flat, guarded by an operator token that lives with the other secrets (§13.5). This is how the demo shows the behaviour without waiting for the market |
| **Re-check at confirm time** | Before either calendar entry is written, the flag is read again. If it flipped, **the booking does not happen**: the flat is dropped from the shortlist, the renter is told plainly, and the remaining shortlist is re-read to them |

**This is a different re-check from the calendar one (§10.2).** Free/busy asks *"is the owner free at 4pm?"*; this asks *"is this flat still on the market at all?"* Both run at confirm time, both can send the renter back, and confusing them is how a demo ends up booking a visit to a flat that no longer exists.

**[AD-11] The flag lives in an in-memory overlay, not in the artefact bundle.** The bundle is read-only at runtime (§5.2) and there is no database (AD-7), so the toggle writes to a small in-process map that shadows the dataset's value, and it dies with the process — a restart returns every flat to the state the import found. That is honest demo scope: it keeps "no database" true, and the only thing lost on restart is a demonstration toggle, never a booking.

---

## 9. Explaining, with sources

This is where the zero-invented-facts requirement is either won or lost. Four components, in order.

```mermaid
flowchart LR
    Q["'Why this one?'"] --> RS["<b>1. Retrieval</b><br/>only this area's<br/>document chunks"]
    RS --> RES["<b>2. Resolvers</b><br/>one source per<br/>kind of claim"]
    RES --> J2["<b>3. Job 2</b><br/>phrases the facts<br/>it was handed"]
    J2 --> CA["<b>4. Assembler</b><br/>every sentence must<br/>trace to a fact —<br/><i>others are dropped</i>"]
    CA --> VM["Screen: text,<br/>citations, labels"]

    classDef q fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef step fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef model fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef out fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    class Q q
    class RS,RES,CA step
    class J2 model
    class VM out
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1k01vozAQhv_KiBxyIR9APlQUsYraXqLtoYnUHpY9DPawWDGY2qZpVPW_rwNpiiKF28x4nvedsfn0mOLkxeDlUh1YgdrC721agfue_6Te8LU4gi2EAVXRr2Hq_YXRKIHtztVWWRKMYUtWC3pHuZpkySrTk0RV8tyDmnBo2iRXrCmpssCKptobB-pEtrsO-HgmhieiUfKdtOkRCYxqNCOoSbepvag4qByYRFH-0B473CbsaNEYNiqD8EKqC42GjLNHkCOznTlh4YAGCqw48QtsE7as-3XHmo1hbQyVmXQWvnnkfB7BuMGocu7Kxtg2bzW60CrAVgbSJpwGs7a0Eoly8rpdD3Ct6pr4aiKSi_D9uhV-eXLCO6aJqhgsfVi_7WfCohWqMj5IzEh2u-w63TaMeaAc3iAXUsYDnhHm5Bur1Z7iQThfRJSdw9FBcFvEYf3hMyWVjgfTLMgivEIZS_U3jeWMlhdasMBohrdp85CCxRWtdM9NnnE55RH7wfG75XK6uImbzQOcRlc41dgzjDjd9SZdsgiJ34Q5Z9PFvAeDZ3jrh9ud7x6T767iNH-_4p5FO0Q_9_J0cuL54JWkSxT89Ed9pp6755JSF6QepxwbaVPv63QMG6t2x4q5ktUNuUxTc7T0IPCfxvKc_voPGkQqRA) — zoom, pan and export</sub>

### 9.1 The RAG pipeline, end to end

The four boxes above are only the live half. The full pipeline has **two halves that run days apart**, and it is worth seeing them in one picture — the build half decides what the system is *able* to say, and the question half decides what it *does* say.

```mermaid
flowchart TB
    subgraph OFF["Build time — days before the demo, offline  (§3)"]
        direction TB
        G1["<b>1. Collect guides</b><br/>1 to 3 per area, from Wikipedia<br/>and open city guides"]
        G2["<b>2. Chunk semantically</b><br/>split where the <i>meaning</i> shifts,<br/>not every N characters"]
        G3["<b>3. Embed each chunk</b><br/>turn text into a vector"]
        G4["<b>4. Store in ChromaDB</b><br/><i>one collection per area</i>"]
        G1 --> G2 --> G3 --> G4
    end

    G4 ==>|"ships as a<br/>read-only file"| DB[("<b>The guide index</b><br/>every chunk of every guide,<br/>each with area, title, URL, date")]

    subgraph ON["Question time — inside one turn: first audio by 1.5 s, checked text by 6 s  (§9.2 to §9.4)"]
        direction TB
        Q1["<b>5. Embed the question</b><br/>'is Indiranagar noisy?'"]
        Q2["<b>6. Search one collection</b><br/>the area of the listing<br/>being discussed — <i>and nothing else</i>"]
        Q3["<b>7. Take the top few chunks</b><br/>each still carrying its<br/>title and link"]
        Q4["<b>8. Job 2 phrases them</b><br/>fenced off as untrusted data;<br/>facts in, sentences out"]
        Q5["<b>9. Check every sentence</b><br/>no resolvable citation,<br/>no sentence"]
        Q1 --> Q2 --> Q3 --> Q4 --> Q5
    end

    DB -->|"read-only,<br/>loaded once at boot"| Q2
    Q5 --> OUT["Answer on screen and aloud,<br/>every claim traceable"]
    Q3 -.->|"nothing found"| GAP["<i>'I don't have neighbourhood<br/>data for that area'</i>"]

    classDef build fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    classDef store fill:#cffafe,stroke:#0891b2,stroke-width:3px,color:#083344
    classDef live fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef model fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef out fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#4c0519
    classDef gap fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    class G1,G2,G3,G4 build
    class DB store
    class Q1,Q2,Q3,Q5 live
    class Q4 model
    class OUT out
    class GAP gap
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNqNVl1v2zYU_SsXzkNaQHGsD9uxl3pIltXoMLTVmmIPdR8o8coiLJMeScUx2v73XYqy_FFkmBBAskidc3juuWS-9XLFsTeFXlGpbV4ybeHxfiGBLlNnS802JXx4-_bLondfi4qDFWuERR0NwgQ42xnIsFAawZYIHNcqAFUUlZAI8GpRDwZsHL9e9L56RHdxoTG3QsmOx13zkBhus1nYh99UVdEMWNaCo7m9zma3mb6ehWAVxLBBDUwjC6DQag1_i5XYIBesmcMkB7VBCbmwuxbghHweeZqIaMparsDgmkkrclZVu47KbCphYVtiu65bMVsjk0Iub6_FDEwpCmuCZqpUFvAJ9Q7eg3OP5Rb1GWfsOeM-_L7OkAOyvKTJRN8x2lpLsPhsQUhaJoMnckDpU5zE4yR9-GSd5ULSIsgE9nDfAZFURd7n3kPn8t4wJ_0UL4SrqxlZ4m-xvyV-Akq-kP5xnsCbN7Pvix6te2OA0V9DRZj8SslqB4WocNH7Dg_3X141Eh_JtMZ90sjxuVPnnWqWTjFpjWsmejcbZ7bClm2JrbAVBvD5rz8DCpslktdf97IO6XxPvqQ1mma5x_kU0jgNzhBn8JSEamOB1VwoyHYQ9odgAtKD-Yrq0vhPr0dguvBO-pHL3f5H8n-ynLZZHu4L7jL0Tyuw8-JSGHgnCYFJtmQapBJm9-vlCX7axnVEJUemyZzT4h7yQwzOMueqe64EkVFc3ViG9ERSTV4bQ2pacygprl0owKUbx8rgTxFJ2-iO-_DIVr4ZrNpAgVtfxUN7NqUj0qqCnGm9c5jCGq_OlREcG20Mq1OGNtQ3ffhDZRDBptTMoHFU6w68QJmTctpZXPxqaXVtLL2gTLBf_AxqPEMFD6ijpXXTDajannINPdfENT-VvM3f_oOOTSrQaFT1xDKSTVsJc17v-72bf4rtmyn1zZT6ZkoTfxv-1FMP926EeqprIg9fKcbdQgkeGIVRKesaK438Z-mwAfzw-ZFWcifNlnqbwmdyjbTpOYNZpWoeHDdbxcQaLG1M6JbTiXYS-42EfQIKVZNAYpvffXRGidnlO-BKXloo2ROCRLEsM1XrUineMDj76TNNxSKxLn-XXYQ8C7Eb84AFZM3hQRtFNb1AjpMCA2O1WuH0YpzHDHn782oruC2n0eY5oJgrPb2IMByMhmdwptkAPVxeFOwIbnAzCbPoFC4-wA1u4jhJzuAq8bRH43mR47hDC0csTtiL4gZDkjc6Q1vTiVq1cAUWcX6A45PxeDB6ES4ZhmwQn8FRjPdgBSY46sAwDHly8zJYPhiGkzOwJdt0yjDC6KAsj0bRfykbsAE7AqPjI5hHwTwO6Hxoqns8SPluSnT8Lg2DNArSOKAUO8NPxhLv2vE7SnnTwsecdx_dCnoB9Nao10xw95_Lt0XP7RaU7SksehwLVlfUNj_cNFZb9WkncxqiTYPOkl69cSfJg2B0eqzb1z_-BQJg3EA) — zoom, pan and export</sub>

**Reading it in one line:** guides are cut into chunks and stored once; a question is turned into the same kind of vector, matched against **only its own area's chunks**, and the few that come back are the *only* material the model is allowed to speak from.

#### The three choices that shape this pipeline

**Semantic chunking, not fixed-size.** A guide is split where the **meaning changes** — paragraph and topic boundaries measured by how much the text drifts — rather than every N characters. Fixed-size splitting is simpler, but it cuts sentences in half and mixes two topics into one chunk. That matters more here than in a typical RAG system, because a chunk is not just retrieval material: **it is what gets cited**. A chunk that begins mid-sentence or straddles two subjects produces a citation that does not properly support the claim attached to it, which is an automatic failure at sign-off. Semantic chunks stay readable on their own, which is the same property a citation needs.

**ChromaDB, embedded in the backend process.** Chroma runs as a library inside the Python process, loading a persisted directory at start-up — no server, no network hop, nothing else to deploy. That is exactly what **[AD-4]** requires: for a corpus of a few dozen documents, a hosted vector database would put a network round trip inside the 1.5 s first-audio budget and add an outage the demo does not need.

**[AD-10] Dense embeddings — a small English sentence model — not sparse, hybrid or anything heavier.** Retrieval matches on *meaning*, using vectors produced by a compact English model that runs in-process. Two things decide this:

- **Semantic chunking already requires an embedding model.** Splitting a guide where the meaning shifts means embedding adjacent passages and watching the similarity drop. A dense model therefore exists in the build pipeline whichever retrieval method is chosen — so dense retrieval costs **no extra machinery**, and the same model that cut the chunks also embeds the question.
- **Spoken questions share almost no words with guide text.** A renter asks *"is it noisy?"*; the guide says *"a residential locality known for its pubs and nightlife"*. There is no token overlap at all. Keyword matching scores that pair near zero; a dense model scores it high. Transcribed speech is the case sparse retrieval handles worst.

The usual objection to dense retrieval — that it is compute-heavy — is an argument about web-scale corpora. Here, build-time embedding covers a few hundred chunks, and at question time the system embeds **one short sentence** against a collection of perhaps 10 to 40 chunks. A small model on CPU does that in tens of milliseconds, well inside the 1.5 s first-audio budget.

**Why not the alternatives:**

| Rejected | Because |
|---|---|
| Sparse (BM25) | Its one strength is exact proper nouns — and the area name is handled by the partition, so it never needs matching |
| Hybrid | A second index and fusion weights, to reorder about twenty chunks. Held as the escalation below, not built now |
| Domain-adapted | Needs in-domain training data. The dataset is a supplied spreadsheet, not a labelled corpus (§16) |
| Multilingual · Cross-modal | English only is explicit MVP scope; the corpus is text |
| Hierarchical · Fusion-based | Built for long documents and large heterogeneous corpora. This is neither |

**The one thing that would change this:** grounding-suite failures on exact-token questions — a society name, a mall, a road that appears verbatim in a guide but that a dense model blurs. If Suite C shows that pattern, add keyword matching alongside and fuse the two rankings, i.e. graduate to **hybrid**. That is a contained change: collections stay per-area, the partitioning guarantee is untouched, and only the ranking step moves. It is deliberately left as a trigger rather than built up front.

**[AD-9] One Chroma collection per area, not one collection with an area filter.** Chroma would happily hold every chunk in a single collection and accept `where={"area": "Indiranagar"}` on each query. This design refuses that. A filter is an argument that can be forgotten, mistyped, or applied after a broader search has already happened; **a separate collection per area means the other areas' text is not in the set that was searched at all.** Cross-area contamination stops being a bug that testing might catch and becomes a thing the code cannot express — which is what §9.2 means by *partitioned, not filtered*, and what the two contamination probes in the grounding suite actually test.

#### What is settled, and what is not

| Stage | Decision | Status |
|---|---|---|
| Chunking | **Semantic** — split on meaning, not character count | Decided |
| Vector store | **ChromaDB**, embedded (in-process, persisted to a file) | Decided |
| Partitioning | **One collection per area** | Decided — [AD-9] |
| Embedding strategy | **Dense**, a small English sentence model running in-process | Decided — [AD-10] |
| Which model, exactly | A compact English model — `e5-small-v2`, `gte-small` and `all-MiniLM-L6-v2` are all reasonable — **pinned to an exact version** and used identically on both halves. Vectors from two different models make the search meaningless. Confirm what the pinned Chroma version defaults to and set it explicitly, rather than inheriting a default that can move | **Open** — pick during §3, pin it in the manifest |
| Chunk boundaries and how many chunks a question retrieves | Tuned against the grounding suite | **Open** — the suite is the judge, so these are set when it exists (§14) |

**One thing this table does *not* affect:** cross-area leakage. That is prevented by searching a single collection (**[AD-9]**), not by how well any model ranks — so the embedding choices above can be judged purely on answer quality.

---

### 9.2 guide retrieval — partitioned, not filtered

Step 6 of the pipeline above, and the step that carries the grounding guarantee. Retrieval creates nothing and fetches nothing — it **selects a handful of the chunks already sitting in the index**.

A question about a listing in Indiranagar can **only ever see Indiranagar's chunks**. The area is the key the index is partitioned by, not a filter applied to results afterwards.

Why a partition and not a filter is argued under **[AD-9]** above; the short version is that the other areas' text is **not in the set that was searched**, so contamination is something the code cannot express rather than something a test might catch.

**[AD-4] The guide index runs inside the backend process.** The corpus is a few dozen documents. An in-memory index loaded at start-up beats a hosted vector database on latency, on operational surface, and on the 1.5 s first-audio budget it would otherwise sit inside.

### 9.3 The resolver registry — the source rules, written as code

```mermaid
flowchart LR
    C1["Listing fact<br/><i>rent, floor, parking</i>"] --> R1["Dataset resolver"] --> D1[("Imported dataset")]
    C2["Amenity or transit"] --> R2["OSM resolver"] --> D2[("Precomputed<br/>map facts")]
    C3["Neighbourhood<br/>character, safety"] --> R3["Document resolver"] --> D3[("This area's<br/>chunks only")]
    C4["Anything else"] --> R4["Unavailable resolver"] --> D4["Declares:<br/>'I don't have that'"]

    classDef claim fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef res fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef store fill:#cffafe,stroke:#0891b2,stroke-width:2px,color:#083344
    classDef none fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    class C1,C2,C3,C4 claim
    class R1,R2,R3,R4 res
    class D1,D2,D3 store
    class D4 none
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp1k11vmzAYhf-KRS6ySY4aDMk6FEWaws2k7kNkuyq9eDEvwQrYyDbpoqr_fXa-RNOGK_A5fs57LPMScFVikJCgatQzr0Fb8pDlkrhnFT7mwYMwVsgNqYDbRaHvlgux1CgtJW6D0pR0oLfOsLgTyzx4IpPJkmR-YwoWDFqi0ahmh_ospuHjpzxYcw0dlqQ8uvLg89MplLm931qUwu6J0sRqkEbYC9rLv9Y_3mOZx_7WyFXb9RbLw7AtdIfJzSAgcoSfKDZ1oXpdK3V0-urOiK6RgQrt_pLo_anivZvpgzaRj_1TC0NAI4zNCdbLrSFKNvtBcOybyb2t_XliY_AS4ZW_EnYgGigafJ_iDSnyxmWY5BAx_k5KJceW1LBDYmuwY-fO5THLOY1JsfIvoiWVaJpkVBbomlFjtdpiMmKzeYTF6XPyLEpbJ6z7R7lqlE5G0yIsIrjCufgzjFccv1xg4RyiGG7DZgzD-RXMWKXxhONVNZxtev81LNht3H0UxfEVTip5plWIDNmFVnI2Z_ObtHg2hemwqbv5dMXoKqKr-HiCQzELacZoFtEs9ucxlNKQpoym0bHaGyU-zBdQErSoWxCl_-de8sDW2LqLkJA8KLGCvnFX_dXboLdqvZfcSVb36Fb6zv0tmArYaGhPy6__AcFYNOE) — zoom, pan and export</sub>

**Job 2 can reach no data except through a resolver**, and every resolver returns a wrapped fact. The grounding boundary is therefore a **dependency rule the code enforces**, not a sentence in a prompt that a model may or may not honour.

A resolver that would have to invent something returns `null` with `source: NONE`, and the assembler renders that as an open gap — *"I don't have safety data for this area"* — which is a correct answer, not a failure.

### 9.4 The assembler — the last gate

Job 2 does not return prose. It returns a list of `{sentence, which facts it used}`.

The assembler then binds each reference back to the wrapped fact that produced it, and **discards any sentence whose reference does not resolve**. An unciteable sentence never reaches the renter. This single rule is also the reason prompt injection has nowhere to go (§13.4): text smuggled into a listing description or a document chunk cannot produce a citation, so whatever it says is dropped before anyone hears it.

The View-Model Builder then draws the card, the neighbourhood panel and the Sources entries **from those same objects**. That is why "all three layers name the same method" is guaranteed by construction rather than tested and hoped for.

### 9.5 A Type B turn, step by step

```mermaid
sequenceDiagram
    autonumber
    participant TO as Orchestrator
    participant RS as Retrieval
    participant RES as Resolvers
    participant J2 as Job 2 (Anthropic)
    participant CA as Assembler
    participant TTS as Smallest.ai
    participant FE as Frontend

    Note over TO: acknowledgement already sent ⟵ L1
    TO->>RS: question + which listing
    RS->>RES: this area's chunks and facts
    RES-->>TO: wrapped facts only
    rect rgba(234, 179, 8, 0.18)
    TO->>TTS: opener built by code from those facts ⟵ P8, L3 under 1.5 s
    end
    TO->>J2: facts + chunks, fenced off as untrusted data
    J2-->>CA: sentences, streaming
    CA->>CA: bind each claim, drop the unciteable
    CA-->>TTS: each sentence, once its citation resolves
    rect rgba(34, 197, 94, 0.16)
    CA-->>FE: text + citations + labels ⟵ L5 under 6 s
    end
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNptk0Fv4jAQhf_KKJctaooWWkrJoRJi4YDQsgKOuUycCVh17KztlEVV__uOkxShQm4TfzN572X8EQmTU5RA5OhvTVrQL4l7i2WqgR-svdF1mZFt6wqtl0JWqD3s1oAO1lYcyHmL3txgNtvAbMhbSe-obgDzjnBGvZN118RyGIClyWAId1PtD9ZUUvSuwdk0gFPnqMzUTcG75lvbEpViyX2U18xiHpCFNdqTzlPdEr-NJzCsj00ngOJNm6OifE8lcQ8qS5ifwIUirYfjYgSrQdu5Wz-8vm62CXC4zkuj4R6OBykOoCTXet9im23A5sz5g3SAPPCHA3Go9RtXOocChe_CYeyB6aDkaLGqqDsFo9WpRSwJD3af4d3w8SmGwXgSw0sMP_uDl96FLg4kAVORZmNZLZWH7ARhH6CwpmQpxlE3u7P1h6esHqHWObcM-iPoNDVZnecuh0nXdt95iKEIu5WDKYoQcK29rZ3nFzl6bFuXw2BrNk2aIAPObbxZhOU5p9m0QzLJoRByjkKhLGPIeS1YMfFoIT0hr8C55ctqw38NjzkvQSBZJTdg829su4bue4pNiJNxDJOnJsXn3uXsxZx_G_3zwW03KThXmJE6J7cadak9X2QWxRCVZEuUebiCH2nEDkpKuUijnAqslU-jz4CFm7g9acFHHB2rj-qKs_u6rt3rz__Uvjlq) — zoom, pan and export</sub>

**Two clocks, deliberately.** Sound starts with the **code-built opener** (P8) — *"It's ₹38,000 for a 2BHK, 1.2 km in a straight line from your office. On the neighbourhood —"* — every word a wrapped fact the resolvers had already handed over, spoken while Job 2 is still producing its first token. Job 2's own sentences follow, each one only after the assembler has resolved its citation. L3 measures when sound starts; L5 measures when the fully checked text and its citations are on screen. They are different budgets because they are different promises.

---

## 10. Booking, cancelling, rescheduling

### 10.1 The states a booking moves through

Four states, and the main line runs straight through the middle: **offered → confirming → booked → done.**

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Offered: three free hours read from the owner's calendar
    Offered --> Confirming: renter picks one
    Confirming --> Booked: free/busy re-checked, both entries written
    Confirming --> Offered: that hour was just taken, offer three more
    Confirming --> Withdrawn: the flat came off the market
    Booked --> Booked: rescheduled, same code
    Booked --> Cancelled: code given, cancellation confirmed
    Booked --> [*]: the hour arrives

    classDef offer fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef mid fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef done fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef bad fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    class Offered offer
    class Confirming mid
    class Booked done
    class Cancelled,Withdrawn bad
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp9U8Fu2zAM_RXCOQwYHCxxGgfzYYe1xwEDtsMO8w60RMVaZCmg5HpF0X-fZLtJlrbzwYBIvqf3SOoxE05SVkHmAwa607hn7Jb3RW0hflIziaCdhS_fpsjP979gufwEX5UiJllBaJkIVPq1rmcPTCjj2XUxReAGS_zOg0BDViJPLDN6ZLp1VmnutN1XEWsDMRy1OHhwlqbqc8UI-OzcId2c7vzQ9P4hwpaiJRGjOTQutBBpWJOHgXUIZF-luXCAYdQOA3r43fsAAQ9kc3CpZHbYOX5dzg8dWsk42Go0rExkE9hRQo-RDvlAYcJO2v-xweSjeNmbpN4nYBrJi_JbtIKMSYiUh72-TxLFFMZxSGJSRvIFOo5tkjf6ROaI9vXcGGHQ-ztSs1-ljakWsiFUlPvAkaRaFNtyQ818XA5ahrYqjn9y4YzjarFq1s0Gr-g6LWcyRWojdicy-XG3W5Vvkt1s17jaXJHJuA7P0oQSdGZbl7i5wbelbQtal1dsDZ6lUUHFWZooyuJ_0la4uvR5WuWxd5eJizWJjbjMzHORpwWfAc8Tzk8rlXRmOWQdcYdapnf6WGdxjh3V8VBnkhT2JtTZUyrDPrjvD1bEVOCeYqQ_yvOznsNPfwH8WVJi) — zoom, pan and export</sub>

| State | What it means | What can happen next |
|---|---|---|
| 🟦 **Offered** | Three free hours have been read from the owner's calendar and read out to the renter | They pick one |
| 🟨 **Confirming** | They have picked, and the system is **re-reading free/busy before writing anything** | Both entries written → **Booked** · someone else took that hour first → back to **Offered** with three fresh ones · the flat came off the market → **Withdrawn** |
| 🟩 **Booked** | The visit exists in both calendars and the renter has the 6-character code. **If only one of the two entries landed, it still counts as booked** — the missing one is retried in the background, and the renter is never asked to wait for it | Reschedule (the code stays the same) · cancel · the hour arrives and it closes quietly |
| 🟥 **Withdrawn** | The flat came off the market before the entries were written (§8.4). Nothing is booked | The renter is told, the flat leaves the shortlist, and what remains is read out again |
| 🟥 **Cancelled** | Both calendar entries are removed. The code then answers **exactly as an unknown code does** — see §10.2 | Nothing. A new visit is a new booking with a new code |

Slots come from the owner calendar's free/busy: the **next 7 days, 10:00 to 18:00 IST, one hour each**, with the first three offered. Cancelling and rescheduling are both refused once the hour has started, and both may happen more than once before then.

**Why "reconciling" is a note and not a state.** From the renter's point of view a confirmed booking is made the moment they confirm — that is what §10.2 means by their intended state being authoritative. A calendar write that did not land is repair work happening behind the scenes, not a different state for the booking to sit in.

### 10.2 The four mechanisms that carry the correctness

| Mechanism | What it prevents |
|---|---|
| **Free/busy is re-read at the moment of confirmation**, never trusted from when the slot was offered | Two renters racing for the same slot. The one who loses is simply re-offered, and neither is ever told a booking exists that does not (spec §6.41, §6.42) |
| **Both calendar entries are written at the same time**, with anything that failed queued for retry (P6) | A half-booked visit. The **renter's intended state is authoritative** from the moment they confirm; the system reconciles the calendar behind the scenes. Rescheduling is four calls, and without parallelism L7 would be Google's latency multiplied by four |
| **Every date calculation names `Asia/Kolkata` explicitly** | The backend deliberately runs outside India, so **any use of the server's local clock is a live bug** (spec §6.47). A lint rule banning naive timestamps is worth the five minutes it takes to add |
| **Unknown codes and cancelled codes get identical answers**, and lookups are rate-limited | Someone guessing codes to enumerate other people's bookings. The code is the only credential there is — the specification is explicit that this is a demo-scope limitation, not a solution (spec §6.45). *Identical* is literal: the same 404 and the same sentence, so a cancelled code cannot even be distinguished from one that never existed. An earlier draft of §10.1 said a cancelled code "answers cancelled"; that would have been a working oracle for guessers, and the specification wins (spec §6.9) |

### 10.3 The confirmation itself

On confirmation, a PDF is generated, emailed to the renter through Gmail, and then **discarded** — nothing is retained. The owner's contact on it is the labelled placeholder `999999999`, deliberately invalid so nobody dials a real number.

Two rules worth stating plainly:

- **The email address is read back character by character before sending.** It is the highest-error input in the whole system, and a wrong address fails silently otherwise.
- **The code is authoritative, not the PDF.** If the email never arrives, the booking still exists and the code still works.

---

## 11. What the renter sees

```
app/
├── audio/          microphone capture · playback · interruption · unlocking sound
├── transport/      WebSocket client (reconnect, backoff) · HTTP client · contract check
├── viewmodels/     types from the shared contract package — nothing is worked out here
├── components/     cards · neighbourhood panel · sources · mic · booking · failure states
└── state/          session store (temporary, mirrors the backend)
```

**[AD-5] The frontend works nothing out for itself.** It receives finished view-models and draws them. No distance formatting, no method labels, no substituting "not stated" for a blank — all of that arrives already decided from the backend.

This is what makes the grounding suite's assertions on view-models sufficient without screenshot testing. If the assertion passes on the view-model, the only remaining way to get it wrong is a rendering bug in a component that contains no logic to be wrong about.

**What the cards must show** (spec §4): the area name (the specification's `locality`) as the primary label with the society name beneath it, then rent, **deposit and maintenance** (the real cost, visible up front), size, floor, parking, furnishing, amenities. Unstated fields read *"not stated"* — never blank, never zero. **A commute row's method badge is never dropped for space**: if the card is tight, the number comes off, not the label.

**Three audio behaviours the specification's failure list demands:**

| Behaviour | Why |
|---|---|
| Sound is unlocked by the renter's own click on the microphone control | Browsers block autoplay; without this, the first answer plays to nobody (spec §6.15) |
| The microphone keeps capturing **while** the system is speaking | Otherwise interrupting is undetectable (spec §6.17) |
| Switching browser tabs pauses capture, but is **not** treated as "finished speaking" | A backgrounded tab must not submit half a sentence (spec §6.16) |

### 11.1 What crosses the wire

The two hosts deploy independently (§13.2), so the messages between them are a **versioned contract**, not an implementation detail. There are deliberately few of them.

| Channel | Message | Direction | Carries |
|---|---|---|---|
| WebSocket | `hello` | browser → backend | The contract version the frontend was built against. A mismatch closes the socket with a clear message rather than failing later |
| WebSocket | `audio` | browser → backend | Microphone frames, streamed continuously — including while the system is speaking, so interruption is detectable |
| WebSocket | `transcript` | backend → browser | Partial words as they arrive, then the final line |
| WebSocket | `ack` | backend → browser | The L1 moment: final words plus the thinking indicator. Sent **before any model is called** |
| WebSocket | `audio_out` | backend → browser | Synthesised speech, chunked, starting on the first sentence |
| WebSocket | `outcome` | backend → browser | Exactly one of the five shapes in §12.1. When it is `Answered`, it carries the finished view-model — cards, badges, labels, Sources — and the frontend draws it without deriving anything |
| HTTP | `POST /bookings` · `POST /bookings/{code}/cancel` · `POST /bookings/{code}/reschedule` | browser or orchestrator → backend | The three booking actions (§10). The code is the only credential |
| HTTP | `GET /health` · `GET /contract` | platform → backend | Railway's health check; the contract version, for the deploy-order rule in §13.2 |
| HTTP | `POST /admin/availability` | operator → backend | The availability toggle (§8.4), guarded by the operator token |

Everything the renter can see arrives in `outcome`. That is the same structure the grounding suite asserts on (§14), which is what principle **A7** (§17) means.

### 11.2 Voice Agent Persona

Everything above settles what the renter *sees*. This settles what they **hear** — who is speaking, and how. It is a design constraint, not decoration: the persona is what makes a stranger comfortable enough to say a real budget out loud, and it is bound by every guardrail in §17.3, not exempt from them.

| # | Element | The rule |
|---|---|---|
| **1** | **Role** | A professional property service agent, experienced at understanding what a buyer or renter actually needs and turning it into useful information for scouting a property against their preferences. |
| **2** | **Identity** | **Nakshatra**, female. Warm and sweet in manner, with a strong working knowledge of Bengaluru real estate. Welcoming, likeable, polite, respectful, empathetic. |
| **3** | **Goal** | Get the renter to a booked site visit: calendars blocked, a 6-character visit code given, and the confirmation PDF emailed — exactly the flow in §10. |
| **4** | **Speech style** | **At most 3 sentences per reply.** Calm, natural pace with short pauses. Everyday language, no jargon. Never a monologue. |
| **5** | **Capabilities** | Acknowledge and appreciate what the renter says; build their preferences up with them; move steadily towards a booked slot. Stay on this project's subject. Never invent — every claim is grounded (**G1**). Take correction gracefully and let it improve the next reply. Keep the conversation engaging and meaningful. |
| **6** | **Privacy** | Never ask for personal or financial details. Rent, deposit and budget are the only money questions. **The single exception is the email address**, asked only at the confirmation step because the PDF cannot be sent without it (§10.3) — read back letter by letter, used once, and gone when the session ends (**G13**). No name, phone, ID, employer, income, or bank detail is ever requested. |
| **7** | **Opening** | The renter clicks the microphone; **Nakshatra speaks first** — greeting, who she is, what she can do, then a request for preferences with one or two examples. **No more than 3 sentences or 150 words.** |

**Three things that make this safe rather than merely nice.**

- **The opener is written by code, not by a model.** It is a fixed template spoken on the mic click — the same click that unlocks browser audio (§11, spec §6.15). So it costs nothing from the L0–L3 budgets (§2.5), and it cannot hallucinate a claim about the dataset before the conversation has started.
- **The persona lives in three places, not one.** Job 1 never speaks, so it carries none of it; the greeting and the conversational replies are code templates that carry the tone; **Job 2's system prompt carries the tone and is still fenced by the assembler** (§9.4) — a charming sentence with an unresolvable citation is discarded exactly like any other.
- **The 3-sentence rule governs conversational turns.** A Type B explanation is the fact-led opener plus the Job 2 sentences that survive binding (§9.5); the persona keeps those short and plain, but the assembler, not the persona, decides which ones are said at all.

---

## 12. When something goes wrong

### 12.1 Five outcomes, and the compiler enforces all five

Every turn ends in exactly one of these. They are five distinct shapes, not five values of a status field.

```mermaid
flowchart TB
    T["A turn ends"] --> A["<b>Answered</b><br/>here is the result"]
    T --> E["<b>Empty</b><br/>nothing matched, and here is<br/>the requirement that was binding<br/><i>this is a RESULT</i>"]
    T --> D["<b>Degraded</b><br/>part of the answer, and<br/>what is missing"]
    T --> F["<b>Failed</b><br/>this capability is down,<br/>here is what that means<br/><i>this is an ERROR</i>"]
    T --> N["<b>NeedsInput</b><br/>a question back<br/>to the renter"]

    classDef base fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,color:#111827
    classDef ok fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef warn fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef err fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    classDef ask fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    class T base
    class A ok
    class E,D warn
    class F err
    class N ask
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp9k1FvmzAQx7-KRV6JAqSBLooiZUoiTZoyKW2flj0c9lGsgE1tIxZV_e4zBlHG2iFe7rj73f_vw68elQy9NfGyQjY0B2XI49eLIPZ5_HnxdsTUShAUTF-8X2Q-35KdTW_S7U7oBhWyzSLdblK12OY2IlwTkyNRqOvC2I6e5BoPXeOhrMxt6BLS5Fw8kxIMzZH5BAQjPcoVdLiXmissURiLB0Ma0CTlgtlOV7Thts7Oti-Q8-Hh6fvjZsG3EwH7TsAenxWwkfKqdS0zpxycLSfDfWvacRZbcq3ttAnx2BGPwIsRz0mhUEHKC25ubTuTjfD_OiYHdmZKtEP_sSHI4Xz-cf7AxqkbekJk-puoajMMBvJSozZcCpICvXZiZL8RYVA5UseiBWi9x8xWaiQZL4r1DFeYYOpro-QV17M4TaL7oA_nDWcmX0fVb5_KQqr1LAzD-yiZ0OS1ZzGaUUwGVhjD8g4-ZQWrCMN4wmrA_nodLcNsSd9p7EuSBPGntLtVCMFyQkOlBhhGGL3DaBRH_4MFEMAEBnrwmSJkOMCiVbwcjvADn2mYLscwu9N2AePMzh7iOD74e3cU49yxtTNOnFpJnk-8ElUJnLVX-vXi2dWXeLHBxWOYgbuUb20Z1EY-3AS1n4yq0WbqioHBPQd7O8o-_fYH8rdWIg) — zoom, pan and export</sub>

```
TurnOutcome =
  | Answered   { view_model }
  | Empty      { which requirements were unmet, what could be relaxed }   // a RESULT
  | Degraded   { the partial answer, what is missing, why }
  | Failed     { which capability, what to tell the renter, is a retry worth it }   // an ERROR
  | NeedsInput { the question, the field it is about }
```

**`Empty` and `Failed` are different shapes.** That is the whole point. *"Nothing matched"* and *"I couldn't check"* cannot be rendered by the same code path because they are not the same thing, and the compiler forces the renderer to handle each one. Adding a new failure without a message for the renter becomes a build error, not an oversight discovered in the demo.

**`Failed` names the capability that is down** — speech recognition, understanding, explanation, speech output, calendar or mail. The renter is told *which* part is unavailable, not handed a generic error (spec §6.11, §6.23).

### 12.2 What still works when a provider is down

| Down | Shortlist | Explanation | Booking | Voice out |
|---|---|---|---|---|
| **Deepgram** (speech in) | ✗ the turn cannot start | ✗ | ✗ | — |
| **Groq** (Job 1) | ✗ | — | ✗ | — |
| **Anthropic** (Job 2) | ✓ produced by code | ✗ **withheld, never substituted** | ✓ | ✓ |
| **Smallest.ai** (speech out) | ✓ | ✓ | ✓ | ✗ → falls back to text |
| **Google Calendar** | ✓ | ✓ | intent recorded, reconciled later | ✓ |
| **Gmail** | ✓ | ✓ | ✓ the code still stands | ✓ |

**The Anthropic row is why the design uses two model providers.** If Job 2's provider is down, the demo loses one capability rather than everything. And **falling back from Job 2 to Job 1 for explanations is forbidden** (spec §6.11) — enforced by wiring the resolver-and-assembler path to one client only, so there is no code path to fall back along.

### 12.3 Fail at start-up, never mid-sentence

A boot check runs **before the port opens**:

```mermaid
flowchart LR
    B["Process starts"] --> C1{"Every secret<br/>present?"}
    C1 -->|no| X["Exit non-zero.<br/><i>Railway's health check<br/>catches it — not a renter</i>"]
    C1 -->|yes| C2{"Dataset and index<br/>load and agree?"}
    C2 -->|no| X
    C2 -->|yes| C3{"Bundle version matches<br/>the contract version?"}
    C3 -->|no| X
    C3 -->|yes| C4{"Map facts cover every<br/>listing × question?"}
    C4 -->|no| X
    C4 -->|yes| C5{"Embedding model loaded =<br/>the one in the manifest?"}
    C5 -->|no| X
    C5 -->|yes| OK["Open the port"]

    classDef start fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef check fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef bad fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#450a0a
    classDef good fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    class B start
    class C1,C2,C3,C4,C5 check
    class X bad
    class OK good
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp9k01v2zAMhv8K4R52cVZ_JcGCLgPq9tQNGbpLgXkHWqIbobaUSfKarO1_H20njdui88nix8OXpPQQCCMpWEBQ1eZerNF6-HpdaODv_GcRfLdGkHPgPHtcEfyCyWQJefxQBJd_yO7AkbDkz0p7utxYcqT9lyJ4GgB53EU_avMIN8y63CoP2ujJX7LmY59yppbXqOp73H1wsCas_RrEmsRd7xXo-eCA04o2ieKMsz0gWK5C9uxULVnQi1I7co-QJ6zuAj064mgtQWlJ255YG5S9CW8t0UhpclT6wjIAUwaet1rWBNy0U0ZDM2jrqX5NIIz2FoU_BIzY6Rt2OmJnzP6GG6g42TGG84G60Q6ClfNK33L_USTn8LslPr-gZ2_o2Yg-7RbVlCRlR2l41zV0QyAJn5-1G008I-h-G9Sq4hqjAtM3BabHAqsrXuxqQ0P2xljfr2QIFDU6d0HVcHugUnW9OJElYUWh89bc0eIkmc5SKvfHyb2Sfr1INttQmNrYxUlUxmWKr3D9DdnjKqpSMX_GyU_zeTR7F5dNY4zSV7iS78QBRgklR5hIZsn_YBFGr7XdGnOgSVEJOkqLZ5hm-H6n04Ti2YgG58PcxqY8DvMkzNMwz0JeQz-Isf-ma2ZsWF31ioIQgoZsg0p2b50vBa-roYIPRSCpwrbmxT11Ydh682OnBbu8bYkt7UaipwvFbwabvfnpH1CkXL0) — zoom, pan and export</sub>

A missing key discovered at start-up costs a redeploy. The same missing key discovered mid-conversation costs the demo (spec §6.35, §6.55).

---

## 13. Running it

### 13.1 The complete tech stack

```mermaid
flowchart TB
    subgraph FE["Browser — Vercel"]
        F1["Next.js · React · TypeScript"]
        F2["AudioWorklet<br/><i>capture and playback</i>"]
        F3["WebSocket + HTTP clients"]
    end

    subgraph BE["Backend — Railway · one process that stays awake"]
        B1["Python · FastAPI · asyncio"]
        B2["ChromaDB, embedded<br/><i>guide index of area guides</i>"]
        B3["Plain-code engines<br/><i>filter · rank · slots</i>"]
    end

    subgraph PROV["Providers called during a conversation"]
        P1["Deepgram<br/><i>speech to text</i>"]
        P2["Groq<br/><i>Job 1 — fast</i>"]
        P3["Anthropic<br/><i>Job 2 — careful</i>"]
        P4["Smallest.ai<br/><i>text to speech</i>"]
        P5["Google Calendar<br/>+ Gmail"]
    end

    subgraph BUILD["Build pipeline — offline, Python"]
        D1["Importer<br/><i>supplied spreadsheet</i>"]
        D2["OpenStreetMap MCP<br/><i>map facts</i>"]
        D3["Guide indexer<br/><i>semantic chunking<br/>of Wikipedia, city guides</i>"]
    end

    FE <-->|"WebSocket + HTTPS"| BE
    BE --> PROV
    BUILD -->|"versioned read-only files"| BE

    classDef fe fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#0b1b3a
    classDef be fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#052e16
    classDef prov fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#451a03
    classDef build fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#2e1065
    class F1,F2,F3 fe
    class B1,B2,B3 be
    class P1,P2,P3,P4,P5 prov
    class D1,D2,D3 build
```

<sub>[⤢ Open this diagram in a canvas](https://mermaid.live/view#pako:eNp9VV1z2jgU_St3nMeaFGw-pkwmM3Ecst3Ztp6QbR7KPlxL16BFWF5ZDmHa_ve9ApxAaMoTku45OvfoSP4eCCMpGENQaLMWC7QO7pNZCfyrm3xusVrA5ObbLEisWddkYdZE3V4fvpIVpGfBP7ta_5v0uOwzPbnzf2su63bzEdwRCtcO7jcVTYVVlTvGRYy7aqQyD8YuNbmL3L6_vFCXAivXWAIsJVQaNzmK5cV7dXmMjhn9QPnUiCU5eAd_3N9nILSi0tXPlVTKWfmqrWTbFnPyYtvWHSq9xk2r2JQElTWC6hrcAh3UDjc14BqXdKQi8b1nG7cwZYudYO2uso_tEOtNKZQ5RvnOrxfWrDBNQqBVTlKSbPufN0oSqFLSE5gC0BLCdq4-cSHxLmQaVdnxB8r9zlXJdXumQmm3PbutFIvlsv1fa-OO6X5lVXb35avfwJpH3t7WIFBrkiAbq8o5IAhTPvI8OmXKI2GZNyYlqpho1cqpKyKxAGfAcVxOmsm8LbfW_NfW_2ly6LVHVLCvpxDf_1Xp2MtKiUNc1OIE-1c0-hTaZ-h05Ruq3TmqFuyleYk7saewgRdpzFwTXKNm19Buoe_gdsUp-n30_v74V-rT1yjN2VYVaT6uVqkpCj8MYReoo21T7ydfIqzItkpzPm3UjW3OLYf-RGnq7fxSUTl1lsh9wgo-XWcteMXDgi_paaZS7-ntSwZfNqxphaVTAsSiKZecgO0CR_RBLbkXqTAEodzmV2k9sGNyAxedzuWP0_s7nQU_-H7uypIb4KptBvcT3j3YIX3qOHOcRb4dsmNKvQFOO9Utww4iNNZ1SgUU5Jf1-EzmhAWFtbNmSeOzaDCMKd8PO2sl3WIcVU-hMNrY8Vk37-UxvuLKn7lEIWj0zNUbYtzHt7kGEfWGr7j4lXncsxVUxOKFTX4YjbrDN9n6gx5249fKtrna0ZGkDweNjkSMJN-kY2nd4eCAjp_1cBKFk5itO5xOemEShUnMLhxOZ70wi8IsDrN-mA22bR0up70wjcI03ikMQghWZPm6SP8J-j4L3IJW_LKOYRZIKrDR_Kn46cuwcWbKLygvOdvw3QiaSqKjVKF_WfbTP_8Hrq4isQ) — zoom, pan and export</sub>

**Everything the system is built from, and why each piece is there:**

| Layer | Choice | Why this one | Fixed by |
|---|---|---|---|
| **Frontend framework** | **Next.js (React, TypeScript)** on **Vercel** | Draws view-models only. No keys, no provider calls, **no API routes** — a serverless route cannot hold the persistent connections the latency budget needs | [AD-8], P1–P2 |
| **Microphone and audio** | Browser **AudioWorklet** | Captures while the system is speaking, so interruption is detectable; playback is unlocked by the renter's own click | §11 |
| **Backend language** | **Python 3, FastAPI, asyncio** | The build pipeline is data work, OpenStreetMap tooling is Python-first, and both model SDKs are first-class in Python. **The one choice the specification does not constrain** | [AD-8] |
| **Backend hosting** | **Railway**, one long-lived process, sleeping **off** | Holds a persistent Deepgram socket and keep-alive pools. Region picked by measurement, not assumption | P1, P2, §13.6 |
| **Speech to text** | **Deepgram**, streaming WebSocket | Interim words within 300 ms (L0); end-of-speech after a 400 ms silence plus a content-aware hold — the largest term in the 700 ms acknowledgement, and deliberately no shorter. Primed with every area name in the dataset, plus Indian-English amount handling ("35k" → 35000) | P3, P3b, §7.2 |
| **Job 1 — understanding** | **Groq**, `openai/gpt-oss-120b`, `temperature=0` | Latency-critical and needs schema conformance, not reasoning. Drops to a lighter Groq tier if it misses its budget | spec §5.1 |
| **Job 2 — explanation** | **Anthropic**, `claude-sonnet-5` | Sets the zero-invented-facts outcome; off the critical path, so capability beats speed. **No sampling parameters** (the model rejects them), no prefill, thinking effort set explicitly to low | P7, spec §5.1 |
| **Text to speech** | **Smallest.ai**, streaming | Starts on the first sentence, not the finished answer | P4 |
| **Retrieval** | **ChromaDB, embedded** — runs inside the Python process, persisted to a file, **one collection per area** | A few dozen documents. A hosted vector database would add a network hop inside the 1.5 s first-audio budget; a per-area collection makes cross-area leakage impossible rather than merely tested-for | [AD-4], [AD-9], §9.1 |
| **Embeddings** | **Dense** — a small English sentence model, in-process, pinned by exact version, **the same model at build time and question time** | Spoken questions share almost no words with guide text, so keyword matching fails; and semantic chunking needs an embedding model anyway, so dense retrieval adds no extra machinery | [AD-10], §9.1 |
| **Map data** | **OpenStreetMap MCP** — **build time only** | Resolved once per listing against a fixed question list; never called during a conversation | P5, §3 |
| **Calendar and email** | **Google Calendar API + Gmail API**, one demo account, two secondary calendars, single OAuth | Bookings live there rather than in a database of ours | §10, AD-7 |
| **Storage** | **None.** Versioned files on disk, read-only at runtime | No database, no transcript store, no PDF store, no user table | AD-7, §5.2 |
| **Model discipline** | Model IDs **pinned exactly, never a `latest` alias** | An alias that moves overnight silently voids the three-identical-runs guarantee | §13.5 |
| **Eval** | Python harness driving the orchestrator directly, 3 suites × 20 cases, run 3× in CI | Real audio in CI would add non-determinism a 100% bar cannot absorb | [AD-6], §14 |
| **Observability** | One trace per turn, one span per component, named to match the specification's measurement rules | A missed budget must be diagnosable without re-running the demo | §13.3 |
| **Secrets** | Five provider keys and one operator token, all Railway environment variables, checked at boot | None in the frontend, none in the repository. The frontend gets one public value: the backend URL | §13.5 |

**Four choices still open**, because neither the specification nor this document pins them — any reasonable library will do, and none of them changes the architecture:

| Still to pick | Constraint it must meet |
|---|---|
| **Which** English embedding model (the *strategy* is settled — dense, [AD-10]) | Must run in-process, be pinned to an exact version, and be the same model at build time and question time (§9.1) |
| The PDF generator | Must run server-side and hold no state — the PDF is deleted after sending |
| The tracing library | Must produce the span names §13.3 lists |
| The spreadsheet reader | Must strip personal data before anything is written to disk (§3); the supplied sheet carries none |

**Two things to notice about this stack.** First, **two model providers, deliberately** — if one is down, the demo loses one capability rather than all of them (§12.2), and Anthropic's model is not served by Groq, so it is two keys either way. Second, **the only things called during a conversation are the five providers in the amber box** — everything purple happens days earlier.

### 13.2 Deploying two hosts without skew

The frontend and the backend live on **different platforms and deploy independently**. That is the single most likely way a green CI run still produces a broken demo, so four rules apply:

| Rule | What it prevents |
|---|---|
| **The backend is deployed first, always** | The two tiers share a contract (§11.1). Ship the frontend first and it asks for a shape the backend cannot yet produce. Backend first means the older frontend is talking to a newer backend that still honours the old contract |
| **The contract version is pinned, and checked at boot** | A mismatch fails start-up (§12.3) rather than surfacing as a blank card mid-conversation |
| **An explicit CORS allowlist — never `*`** | The backend holds every key. `*` would let any page anywhere drive it |
| **The microphone WebSocket goes browser → backend directly, never proxied** | A proxy hop adds latency inside every budget in §2.5, and Vercel cannot hold the connection open anyway (P1, P2) |

Two settings on the Railway side are part of the contract with §2.5, not preferences: **app sleeping is off** (a sleeping process cold-starts inside L1), and the **region is chosen by measurement** — provider proximity usually beats user proximity, though Smallest.ai being India-based may invert that. Cold start is reported separately at sign-off and never averaged into the budget (§13.3).

### 13.3 Measuring, so a miss is diagnosable

One trace per turn, with a child span per component, named to match the specification's measurement rules exactly: `stt.interim`, `stt.final`, `retrieval`, `llm.first_token`, `llm.last_token`, `tts.first_byte`, and one span per external call.

Every trace carries its turn type, so Type A and Type B are scored separately rather than averaged into one misleading number. **Cold start is its own counter**, never folded into the budget (spec §6.56).

The point of per-component timing is that a missed budget can be explained **without re-running the demo** — you can see which stage ate the time.

Logs carry no personal data and no transcript text (spec §3.2, §5.3): span names and durations, not content.

### 13.4 Keeping imported text from giving instructions

Listing descriptions and document chunks are text from the open internet. They are passed to the model inside explicit delimiters, with a standing instruction that everything inside them is data to be read, never instructions to be followed.

The wording helps. **Two structural facts help more:**

- **Job 2 cannot act.** It has no tools and no write path. There is nothing for an injected instruction to make it do.
- **The assembler discards any sentence without a resolvable citation** (§9.4). Even if the model were momentarily swayed, injected content has no route to the renter's ears.

### 13.5 Keys and configuration

All five provider credentials — Deepgram, Groq, Anthropic, Smallest.ai and the Google login — plus the one operator token for the availability toggle (§8.4) are backend environment variables, checked at start-up. None exist in the frontend; none exist in the repository. The frontend receives exactly one public value: the backend's URL.

**Model IDs are pinned exactly, never to a "latest" alias.** An alias that moves invalidates the three-identical-runs guarantee overnight, silently. The pinned pair lives in config so it is visible in the deployment record, alongside the careful model's explicitly-set thinking effort (P7 — leaving it unset lets the model think adaptively and land on the first-audio budget).

### 13.6 Connections

One long-lived process holds a persistent Deepgram WebSocket and keep-alive connection pools for Groq, Anthropic, Google and Smallest.ai (P1, P2).

Nothing in the pipeline may run as a serverless function: a runtime that starts fresh per request cannot hold any of this (§13.1).

---

## 14. Proving it works

```
evals/
├── fixtures/     a frozen slice of the dataset · frozen chunks · frozen map facts
├── harness/      turn driver (text in, view-model out — no audio)
├── suites/       A: feasibility · B: edit correctness · C: grounding
└── assertions/   view-model matchers · provenance matchers · order matchers
```

| Suite | What it proves | The assertion that matters most |
|---|---|---|
| **A — Feasibility** | Budget, bedrooms and must-haves filter correctly, including boundary values and conflicts | At least one case per schema field, plus a "not stated" case |
| **B — Edit correctness** | A refinement changes only what it should | Untouched listings and their order come back **byte-identical** |
| **C — Grounding** | Every claim traces to the right source | Commute method is asserted at **all three layers** — spoken, badge, full label — and **all three must agree**. Disagreement fails even when each layer is individually well-formed |

**[AD-6] The harness drives the orchestrator directly, skipping speech in and speech out.** These suites test extraction, filtering and grounding; real audio in the loop would add exactly the non-determinism that a 100%-on-three-runs bar cannot absorb. Speech-normalisation cases ("35k" → 35000) are asserted at the point where words become requirements, which is where the logic actually lives. Latency, by contrast, is measured on the **full** path including audio.

**Where determinism comes from:** pinned model IDs, `temperature=0` on Job 1, structured output on both jobs, and frozen fixtures. Job 2 has no sampling controls available at all — which is precisely why the three-run rule exists rather than being a formality.

---

## 15. The decisions, and what was rejected

| # | Decision | What was rejected, and why |
|---|---|---|
| **AD-1** | The build pipeline is a separate offline program producing versioned files | Importing at start-up — a source failure would take the service down, and the dataset would stop being reproducible |
| **AD-2** | The manifest is a build output | Writing the sign-off artefacts by hand at the end — they drift from what was actually built |
| **AD-3** | A pattern-matching router picks the turn type before Job 1 | A model classifier — it spends the acknowledgement budget twice |
| **AD-4** | The guide index runs in-process — **ChromaDB, embedded** | A hosted vector database — a network hop inside the 1.5 s first-audio budget, for a corpus of a few dozen documents |
| **AD-5** | The frontend works nothing out; view-models arrive complete | Formatting in the UI — it puts the method label two codebases away from the number it labels, which is exactly how the two drift apart |
| **AD-6** | The eval harness skips audio | End-to-end audio in CI — non-determinism against a 100%-three-times bar |
| **AD-7** | No database | Postgres or Redis for sessions and bookings — it reopens every retention question the specification deliberately closed (spec §2.5, §3.2, §5.3), and the calendar is already the booking's record of truth |
| **AD-8** | **Python backend (FastAPI, asyncio); TypeScript frontend (Next.js)** | A Node backend. One language across both tiers is genuinely attractive, but the build pipeline is data work, the OpenStreetMap tooling is Python-first, and both model SDKs are first-class in Python. **This is the one choice here that the specification does not constrain** — if the team is stronger in TypeScript, a Node backend satisfies every requirement in this document except the map-tooling convenience |
| **AD-9** | **One Chroma collection per area**, and **semantic chunking** of the guides | A single collection filtered by an area field (a filter can be forgotten or applied too late; a separate collection means the other areas' text was never searched) · fixed-size chunking (cuts sentences in half and mixes topics, producing citations that do not support the claim attached to them) |
| **AD-10** | **Dense embeddings**, small English sentence model, in-process | Sparse/BM25 (spoken questions share no vocabulary with guide text) · hybrid (a second index and fusion weights, to reorder ~20 chunks) · domain-adapted (no in-domain training data exists yet) · multilingual, cross-modal, hierarchical, fusion-based (all solve problems this corpus does not have). Hybrid is the documented escalation if Suite C fails on exact-token questions |
| **AD-11** | Availability is an **in-memory overlay** on the read-only dataset | Writing the flag back into the artefact bundle (it stops being reproducible) · a database for one boolean (reopens every retention question AD-7 closed). Cost: the toggle resets on restart — acceptable, since bookings live in the calendar, not here |

---

## 16. What this architecture leaves open

Stated plainly, so nothing here reads as more settled than it is.

| Open item | What it could change |
|---|---|
| **The supplied spreadsheet carries only 14 of the 23 schema fields** (see `data/SOURCE_NOTES.md`) | The data model (§5), the card layout (§11) and Suite A's coverage all move. The wrapper absorbs a missing field gracefully — it becomes a `null` with `source: DATASET` — but the **vocabulary of things a renter can filter on genuinely depends on what the sheet carries** |
| **The latency budget has not been measured.** L3 leans on P8, and P3's 400 ms window leans on pause timings not yet observed on Indian-English speakers. If the spike misses the targets | The fast model, the hosting region, or the targets themselves change (§7, §8, §9). Component boundaries are drawn so that **swapping the fast model is a config change, not a rewrite** |
| **How many people can use it at once** is bounded by provider rate limits, not by this design | The single-process model is a demo-scope decision. Exactly one thing would have to move to scale horizontally: the in-memory session map (spec §6.57) |
| **Nothing here is measured** | Like the specification's budget, this document is derived from requirements, not from a running system. The first thing that should update it is the latency spike's real numbers |

---

## 17. Appendix — the rules and principles behind all of this

### 17.1 The four rules from the specification

Almost every structural choice in this document exists to make one of these hard to break.

| Rule | In plain terms |
|---|---|
| **Say where it came from** | Every fact names its source, how it was worked out, and how fresh it is. Distances must say *by route* or *straight line* — out loud, on the card badge, and in the full label — and all three must say the same thing. A bare `[OSM]` is an automatic failure. |
| **One source per kind of claim** | Listing details come only from the imported dataset (missing means "not stated", never guessed). Amenities and transit come only from OpenStreetMap. Neighbourhood character comes only from a small, fixed set of documents. Anything else is declared unavailable rather than answered. |
| **Answer fast, or say why not** | Budgets per turn: your words appear as you say them (within 300 ms), the system acknowledges within 700 ms of you finishing, starts speaking within 1.5 s, shows the shortlist within 3 s, books within 5 s. These hold only while the setup conditions P1–P7 hold (see §2.5). |
| **A failure is not an empty result** | *"I couldn't check"* and *"nothing matched"* must never look alike. Nothing is ever invented to paper over a failure, and no operation is left half-done without saying so. |

**How it is checked.** Three test suites of 20 cases each, all 60 passing, run three times in CI, with zero invented facts. §14 describes the harness.

### 17.2 The seven principles this architecture adds

Every structural choice above traces back to one of these.

| # | Principle | What it forces in the design |
|---|---|---|
| **A1** | **A fact carries its own provenance** | No bare number crosses a boundary. Every fact is wrapped (§4) with its source, method and date. A distance without a method label is **impossible to represent**, not merely discouraged |
| **A2** | **The source rules are structural, not written in a prompt** | One resolver per kind of claim (§9.3). The explanation path can only reach data through resolvers, so the grounding table becomes a call graph |
| **A3** | **Anything that can be worked out before the conversation, is** | Import, index and map facts are build-time files (§3). While a renter waits, the system fetches **nothing** |
| **A4** | **The model never decides what is true or what matches** | Job 1 turns speech into requirements. Job 2 phrases facts it is handed. **Filtering, ranking, availability and slot arithmetic are ordinary code** (§8, §10) — testable, and unaffected by a model answering differently tomorrow |
| **A5** | **A result and a failure are different shapes** | The five outcomes (§12.1). "Nothing matched" and "couldn't check" cannot share a rendering path, because they are not the same type |
| **A6** | **State lives where its lifetime belongs** | The conversation is in memory and dies with the session. Bookings live in Google Calendar. There is no database (§5.2, AD-7) |
| **A7** | **Everything the renter can see, the test harness can reach** | The view-model is a published contract used identically by the UI and by the grounding suite (§14), so assertions run against the same structure the renter is looking at |

### 17.3 Guardrails — one index

The rules above are stated in §17.1 and §17.2. This is where each one is actually **held** — the place in the system that makes it hard to break, rather than merely asked for.

| # | Guardrail | Where it lives | What it stops |
|---|---|---|---|
| **G1** | **An uncitable sentence never reaches the renter** | §9.4 — the assembler discards any sentence whose citation does not resolve | An invented fact being spoken, and prompt injection having any route out |
| **G2** | **A fact without provenance cannot be represented** | §4 — the wrapper; a distance with no method label does not type-check | A bare number crossing a boundary and losing where it came from (**A1**) |
| **G3** | **One resolver per kind of claim** | §9.3 — the explanation path can only reach data through resolvers | Listing details, map facts and neighbourhood character being mixed or guessed (**A2**) |
| **G4** | **Nothing is fetched while a renter waits** | §3 — import, index and map facts are build-time files; §2.1 shows no arrow from the backend to a source site | A live fetch blowing the latency budget, or a source being unavailable mid-conversation (**A3**) |
| **G5** | **The model never decides what is true or what matches** | §8 and §10 — filtering, ranking, availability and slot arithmetic are ordinary, testable code | A model answering differently tomorrow and changing what a renter is shown (**A4**) |
| **G6** | **A result and a failure are different types** | §12.1 — five outcomes, enforced by the compiler | *"Nothing matched"* and *"I couldn't check"* being rendered the same way (**A5**) |
| **G7** | **Imported text is data, never instructions** | §13.4 — explicit delimiters, Job 2 has no tools and no write path, and G1 drops whatever survives | Text in a listing description steering the model |
| **G8** | **Free/busy is re-read at the moment of confirmation** | §10.2 | Two renters being given the same slot |
| **G9** | **Both calendar entries are written together, failures queued for retry** | §10.2 (P6) | A half-booked visit that nobody is told about |
| **G10** | **Every date calculation names `Asia/Kolkata`** | §10.2 — the backend runs outside India, so a naive timestamp is a live bug | Slots computed in the server's local time |
| **G11** | **Unknown and cancelled codes get identical answers, rate-limited** | §10.2 | Code guessing used to enumerate other people's bookings |
| **G12** | **Fail at start-up, never mid-sentence** | §12.3 and the boot-time manifest checks | A missing artefact or key surfacing halfway through a conversation |
| **G13** | **No listings database, no transcript store, no PDF store** | §5.2 — state lives where its lifetime belongs | Retention questions the specification deliberately closed being reopened (**A6**) |
| **G14** | **The keys never leave the server** | §2.1 — the browser talks to exactly one address of ours, and every paid call starts there | A provider key reaching the frontend |
| **G15** | **Every guardrail above is asserted, not assumed** | §14 — three suites of 20, passing three times in CI, zero invented facts; suite C checks the commute method agrees at all three layers | A rule holding in the document but not in the running system (**A7**) |

**Read this as the checklist for a change.** If a proposed change makes any row harder to state, the change is the thing that is wrong.
