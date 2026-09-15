"""p99 per stage, per turn type; hard failure if any single request exceeds 2× its target (spec §5.2)."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass, field

# Spec 5.2 as renegotiated at Gate L on 2026-09-06 (data/GATE_L.md). The original
# table read L0 300 / L1 700 / L2 1500 / L3 1500 / L4 3000 / L5 6000; measured on the
# deployed US service the models were quick but ~1.75 s of end-of-speech detection,
# ~0.9 s of TTS first byte and ~1.3 s to Deepgram's first interim were not priced in.
# L6-L8 are unmeasured by the skeleton and unchanged.
TARGETS_MS = {
    "L0": 1800,
    "L1": 2000,
    "L2": 3500,
    "L3": 3500,
    "L4": 5000,
    "L5": 8000,
    "L6": 5000,
    "L7": 5000,
    "L8": 30000,
}


def p99(values: list[float]) -> float:
    if not values:
        return math.nan
    xs = sorted(values)
    return xs[min(len(xs) - 1, math.ceil(0.99 * len(xs)) - 1)]


@dataclass
class ScoreReport:
    p99: dict[str, dict[str, float]] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    # Samples behind each p99, so a row read off the table carries its own sample size.
    n: dict[str, dict[str, int]] = field(default_factory=dict)
    # Rows flagged cold_start: true, per turn type. Never inside p99 or the 2× rule: spec
    # §5.2 P1 says cold start is measured and reported separately, never in these numbers.
    cold_start_counts: dict[str, int] = field(default_factory=dict)
    cold_start: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    # Server trace rows (telemetry.Trace.to_json) carry per-component timings, not L-stages:
    # a trace starts after the ack and cannot see end-of-speech, so no target applies to
    # them. Summarised per turn type and name as {n, median, p99}, in ms.
    components: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.violations


def _component_samples(ln: dict, into: dict[str, list[float]]) -> None:
    for s in ln.get("spans", []):  # every call is a sample: two inserts are two
        into.setdefault(s["name"], []).append(s["end_ms"] - s["start_ms"])
    first: dict[str, float] = {}
    for m in ln.get("marks", []):  # tts.first_byte is marked per sentence; the first counts
        first[m["name"]] = min(first.get(m["name"], math.inf), m["at_ms"])
    for name, at in first.items():
        into.setdefault(name, []).append(at)


def score(lines: list[dict]) -> ScoreReport:
    rep = ScoreReport()
    by: dict[str, dict[str, list[float]]] = {}
    comp: dict[str, dict[str, list[float]]] = {}
    for ln in lines:
        tt = ln["turn_type"]
        if ln.get("cold_start") is True:
            rep.cold_start_counts[tt] = rep.cold_start_counts.get(tt, 0) + 1
            for stage in TARGETS_MS:
                if ln.get(stage) is not None:
                    rep.cold_start.setdefault(tt, {}).setdefault(stage, []).append(ln[stage])
            continue
        rep.counts[tt] = rep.counts.get(tt, 0) + 1
        if "spans" in ln or "marks" in ln:
            _component_samples(ln, comp.setdefault(tt, {}))
        for stage, target in TARGETS_MS.items():
            if stage in ln and ln[stage] is not None:
                by.setdefault(tt, {}).setdefault(stage, []).append(ln[stage])
                if ln[stage] > 2 * target:
                    rep.violations.append(
                        f"{tt}/{stage}: single request {ln[stage]:.0f} ms > 2× target {target}"
                    )
    for tt, stages in by.items():
        rep.p99[tt] = {}
        rep.n[tt] = {}
        for stage, vals in stages.items():
            v = p99(vals)
            rep.p99[tt][stage] = v
            rep.n[tt][stage] = len(vals)
            if v > TARGETS_MS[stage]:
                rep.violations.append(
                    f"{tt}/{stage}: p99 {v:.0f} ms > target {TARGETS_MS[stage]} (n={len(vals)})"
                )
    for tt, names in comp.items():
        rep.components[tt] = {
            name: {"n": len(v), "median": statistics.median(v), "p99": p99(v)}
            for name, v in sorted(names.items())
        }
    return rep


def render_table(rep: ScoreReport) -> list[str]:
    """The per-turn-type p99 table, the violations, cold start and the component timings."""
    out = ["| Type | Stage | n | p99 ms | target ms | within |", "|---|---|---|---|---|---|"]
    for tt in sorted(rep.p99):
        for stage in sorted(rep.p99[tt]):
            v, target = rep.p99[tt][stage], TARGETS_MS[stage]
            within = "yes" if v <= target else "NO"
            out.append(f"| {tt} | {stage} | {rep.n[tt][stage]} | {v:.0f} | {target} | {within} |")
    if not rep.p99:
        out.append("| — | no L-stage rows (server traces carry components only) | | | | |")
    out.append("")
    out.append(f"Violations ({len(rep.violations)}):")
    out += [f"- {v}" for v in rep.violations] or ["- none"]
    out.append("")
    cold = ", ".join(f"{tt} {c}" for tt, c in sorted(rep.cold_start_counts.items()))
    out.append(f"Cold-start rows, reported separately and not scored: {cold or 'none'}")
    for tt in sorted(rep.cold_start):
        for stage, vals in sorted(rep.cold_start[tt].items()):
            out.append(f"- {tt}/{stage}: " + ", ".join(f"{x:.0f}" for x in vals) + " ms")
    if rep.components:
        out += ["", "| Type | Component | n | median ms | p99 ms |", "|---|---|---|---|---|"]
        for tt in sorted(rep.components):
            for name, c in rep.components[tt].items():
                out.append(f"| {tt} | {name} | {c['n']} | {c['median']:.0f} | {c['p99']:.0f} |")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", help="client rows and/or server trace JSONL files")
    ap.add_argument("--table", action="store_true", help="print a Markdown table, not JSON")
    a = ap.parse_args()
    lines = []
    for path in a.paths:
        with open(path, encoding="utf-8") as fh:
            lines += [json.loads(line) for line in fh if line.strip()]
    rep = score(lines)
    if a.table:
        print("\n".join(render_table(rep)))
    else:
        print(
            json.dumps(
                {
                    "p99": rep.p99,
                    "counts": rep.counts,
                    "cold_start_counts": rep.cold_start_counts,
                    "cold_start": rep.cold_start,
                    "components": rep.components,
                    "violations": rep.violations,
                    "passed": rep.passed,
                },
                indent=2,
            )
        )
