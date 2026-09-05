"""p99 per stage, per turn type; hard failure if any single request exceeds 2× its target (spec §5.2)."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field

TARGETS_MS = {
    "L0": 300,
    "L1": 700,
    "L2": 1500,
    "L3": 1500,
    "L4": 3000,
    "L5": 6000,
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

    @property
    def passed(self) -> bool:
        return not self.violations


def score(lines: list[dict]) -> ScoreReport:
    rep = ScoreReport()
    by: dict[str, dict[str, list[float]]] = {}
    for ln in lines:
        tt = ln["turn_type"]
        rep.counts[tt] = rep.counts.get(tt, 0) + 1
        for stage, target in TARGETS_MS.items():
            if stage in ln and ln[stage] is not None:
                by.setdefault(tt, {}).setdefault(stage, []).append(ln[stage])
                if ln[stage] > 2 * target:
                    rep.violations.append(
                        f"{tt}/{stage}: single request {ln[stage]:.0f} ms > 2× target {target}"
                    )
    for tt, stages in by.items():
        rep.p99[tt] = {}
        for stage, vals in stages.items():
            v = p99(vals)
            rep.p99[tt][stage] = v
            if v > TARGETS_MS[stage]:
                rep.violations.append(
                    f"{tt}/{stage}: p99 {v:.0f} ms > target {TARGETS_MS[stage]} (n={len(vals)})"
                )
    return rep


if __name__ == "__main__":
    lines = []
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as fh:
            lines += [json.loads(line) for line in fh if line.strip()]
    rep = score(lines)
    print(
        json.dumps(
            {
                "p99": rep.p99,
                "counts": rep.counts,
                "violations": rep.violations,
                "passed": rep.passed,
            },
            indent=2,
        )
    )
