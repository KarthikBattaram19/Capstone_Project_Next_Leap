"""The per-case assembler drop table, printed at the end of a suite run.

Docs/JOB2_SCORES.md needs "dropped sentences per case" before the third sign-off pass:
the count is what separates "Job 2 is being fenced" from "Job 2 is writing uncitable
prose". Counts and reasons only — the dropped sentence itself never leaves the assembler.
"""

from __future__ import annotations

REASONS = ("no_refs", "unknown_ref", "gap_assertion")


def render(rows: dict[str, dict[str, int]]) -> list[str]:
    if not rows:
        return ["Job 2 assembler: no lane B turns ran, so nothing was bound or dropped."]

    lines = ["Job 2 assembler - bound and dropped per case:"]
    bound_total = dropped_total = 0
    for case_id, counts in sorted(rows.items()):
        bound = counts.get("bound", 0)
        reasons = {r: counts.get(r, 0) for r in REASONS}
        dropped = sum(reasons.values())
        bound_total += bound
        dropped_total += dropped
        why = "  ".join(f"{r}={n}" for r, n in reasons.items() if n) or "-"
        lines.append(f"  {case_id:<10} {bound:>3} bound  {dropped:>3} dropped   {why}")
    lines.append(f"  {'TOTAL':<10} {bound_total:>3} bound, {dropped_total} dropped")
    return lines
