# Implementation_Plan.md — version history

`Docs/Implementation_Plan.md` is always the live copy. Every time it is changed in a way that might not work out, the previous copy is kept here unchanged, so it can be restored in one step.

Since v3 the plan is split in two files:

- `Docs/Implementation_Plan.md` — the decision document (plain language: what, why, in what order, done-when, and the decisions to make).
- `Docs/Implementation_Plan_Addendum.md` — the technical reference for builders (every file, function, field, test and command). Its text is the v2 plan with a new preamble.

| Version | File | Date | What it is |
|---|---|---|---|
| v1 | `Implementation_Plan_v1.md` | 2026-08-30 | The original plan as first written: every task carries its source code, config files and commands inline as fenced code blocks (209 blocks, 9,317 lines). |
| v2 | `Implementation_Plan_v2.md` | 2026-08-30 | Same plan with every fenced code block replaced by prose. Every file path, class, function, field, constant, string, test, command, config key, prompt and comment from v1 is stated in words; only the file-structure tree keeps its fence. Nothing was added, removed or re-decided. This text now lives on as `Docs/Implementation_Plan_Addendum.md`. |
| v3 | `Implementation_Plan_v3.md` | 2026-08-30 | The simplified decision document (about 375 lines): glossary, the rules in plain words, the phase order and why, a table of every decision the owner will be asked to make, and one short entry per task (delivers / why now / done when / decision) pointing to the addendum for detail. Same 39 tasks, same numbering, same order as v1/v2. |

## How to fall back

Copy the version you want over the live file, for example on Windows PowerShell:

`Copy-Item Docs\versions\Implementation_Plan_v2.md Docs\Implementation_Plan.md`

or on any POSIX shell:

`cp Docs/versions/Implementation_Plan_v2.md Docs/Implementation_Plan.md`

Falling back to v1 or v2 makes the plan self-contained again; the addendum can then be deleted or left in place (it duplicates v2).

## How to add a version

1. Before editing the live file, copy it here as `Implementation_Plan_v<N>.md` if that version is not already saved.
2. Make the change in `Docs/Implementation_Plan.md` (and, if the technical detail changes, in `Docs/Implementation_Plan_Addendum.md`).
3. Save the result here as the next number and add a row to the table above saying what changed and why.
