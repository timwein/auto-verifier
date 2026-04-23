"""
Tier-coverage gate (Phase 2 — OpenRubrics alignment).

Enforces the hard-rule / principle taxonomy minimums from the alignment plan:
  - ≥2 hard_rule criteria
  - ≥3 principle criteria

Single-tier rubrics fail the gate. The harness is expected to regenerate with
tier-specific feedback when this happens.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rubric_system.models import (
    Rubric,
    Criterion,
    CriterionTier,
    infer_tier,
)


HARD_RULE_MIN = 2
PRINCIPLE_MIN = 3


@dataclass
class TierCoverageReport:
    hard_rules: int
    principles: int
    untyped: int
    passed: bool
    needs_hard_rules: int
    needs_principles: int

    @property
    def reason(self) -> str:
        missing = []
        if self.needs_hard_rules > 0:
            missing.append(f"{self.needs_hard_rules} more hard_rule")
        if self.needs_principles > 0:
            missing.append(f"{self.needs_principles} more principle")
        return "need " + ", ".join(missing) if missing else "tier coverage ok"


def tier_of(c: Criterion) -> CriterionTier:
    """Return the criterion's tier, inferring from scoring method when absent."""
    return c.tier if c.tier is not None else infer_tier(c.scoring.method)


def evaluate_tier_coverage(rubric: Rubric) -> TierCoverageReport:
    """Count tiers and report whether the rubric meets minimums."""
    hard = 0
    principle = 0
    untyped = 0
    for c in rubric.criteria:
        if c.tier is None:
            # Count untyped (legacy) criteria via the default mapping, but also
            # flag them so callers can surface how much of the coverage came from
            # inference vs explicit declaration.
            untyped += 1
        t = tier_of(c)
        if t is CriterionTier.HARD_RULE:
            hard += 1
        elif t is CriterionTier.PRINCIPLE:
            principle += 1

    needs_hard = max(0, HARD_RULE_MIN - hard)
    needs_principle = max(0, PRINCIPLE_MIN - principle)
    passed = needs_hard == 0 and needs_principle == 0
    return TierCoverageReport(
        hard_rules=hard,
        principles=principle,
        untyped=untyped,
        passed=passed,
        needs_hard_rules=needs_hard,
        needs_principles=needs_principle,
    )


def backfill_tiers(rubric: Rubric) -> Rubric:
    """Lazy-fill ``tier`` on legacy criteria using the default mapping."""
    for c in rubric.criteria:
        if c.tier is None:
            c.tier = infer_tier(c.scoring.method)
    return rubric


def build_regeneration_feedback(report: TierCoverageReport) -> str:
    """Render a short feedback block the generator can consume to rebalance tiers."""
    lines = ["\n## Tier coverage feedback — rebalance before re-emitting criteria"]
    if report.needs_hard_rules > 0:
        lines.append(
            f"  - Need {report.needs_hard_rules} additional hard_rule criterion(a). Hard rules are "
            "violated-or-not explicit constraints (format, length, required entities, "
            "no-hallucination). Use scoring_method binary or penalty_based."
        )
    if report.needs_principles > 0:
        lines.append(
            f"  - Need {report.needs_principles} additional principle criterion(a). Principles are "
            "nuanced quality dimensions (calibration, reasoning depth, trade-off analysis). "
            "Use scoring_method weighted_components, threshold_tiers, percentage, or count_based."
        )
    lines.append("  - Do not pad either tier with trivial criteria. If you cannot produce the "
                 "required hard rules without triviality, decompose the task further.")
    return "\n".join(lines)
