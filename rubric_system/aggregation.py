"""
Implicit LLM-judge aggregator (Phase 4 — OpenRubrics alignment).

Adds an implicit scoring path that hands the full rubric + attempt to a single
LLM call and asks for a reward score plus per-criterion judgments. Paired with
voting@K (K=1 by default, opt-in K=3 or K=5), this gives a cross-check on the
explicit ScoringEngine without replacing it.

Explicit scoring remains the system of record (authoritative for pass/fail,
threshold gating, and QualityGate feedback). Disagreement between the two
aggregators is logged for self_improve consumption — the explicit decision
stands.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Optional

from rubric_system.models import Rubric


IMPLICIT_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial rubric-based judge. Given a task, a scoring rubric, "
    "and a candidate response, produce a strict JSON reward and per-criterion "
    "judgments. Do not refuse, apologize, or add prose outside the JSON object."
)


IMPLICIT_JUDGE_USER_TEMPLATE = """TASK:
{task}

RUBRIC CRITERIA (id — description — max_points):
{criteria_block}

Total possible points: {total_points}
Pass threshold (fraction of total): {pass_threshold}

CANDIDATE RESPONSE:
<<<
{attempt}
>>>

Return exactly this JSON and nothing else. Keep strings concise.
{{
  "total": <float — points earned, 0..{total_points}>,
  "pass_fraction": <float — total / {total_points}, 0..1>,
  "per_criterion": {{
    "<criterion_id>": {{"points": <float>, "max_points": <int>, "note": "<one line>"}}
  }},
  "rationale": "<one or two sentences summarizing the judgment>"
}}"""


@dataclass
class AggregatedScore:
    """Result of one aggregation pass (possibly across K voting samples)."""
    total: float
    max_points: float
    per_criterion: dict[str, float]
    rationale: str = ""
    judge_trajectories: list[str] = field(default_factory=list)
    voting_k: int = 1

    @property
    def percentage(self) -> float:
        return self.total / self.max_points if self.max_points > 0 else 0.0


@dataclass
class BudgetTracker:
    """Track extra LLM calls spent by Phase 3 + Phase 4 per run."""
    limit: int = 10
    used: int = 0
    exceeded_logged: bool = False

    def would_exceed(self, cost: int = 1) -> bool:
        return (self.used + cost) > self.limit

    def charge(self, cost: int = 1) -> None:
        self.used += cost

    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def _render_criteria_block(rubric: Rubric) -> str:
    lines = []
    for c in rubric.criteria:
        lines.append(f"  - {c.id} — {c.description} — {c.scoring.max_points}pts")
    return "\n".join(lines)


def parse_implicit_verdict(raw: str, rubric: Rubric) -> AggregatedScore:
    """Parse a single implicit-judge response into an AggregatedScore.

    Tolerates code fences and prose wrappers. Falls back to a zero-score,
    empty-per-criterion result on unparseable output.
    """
    text = raw.strip()
    # Strip markdown fences if present.
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if m:
        text = m.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return AggregatedScore(
                total=0.0,
                max_points=float(rubric.total_points),
                per_criterion={},
                rationale="parse_error",
                judge_trajectories=[raw],
            )
        try:
            payload = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return AggregatedScore(
                total=0.0,
                max_points=float(rubric.total_points),
                per_criterion={},
                rationale="parse_error",
                judge_trajectories=[raw],
            )

    if not isinstance(payload, dict):
        return AggregatedScore(
            total=0.0,
            max_points=float(rubric.total_points),
            per_criterion={},
            rationale="parse_error",
            judge_trajectories=[raw],
        )

    total = float(payload.get("total", 0.0)) if isinstance(payload.get("total"), (int, float)) else 0.0
    rationale = payload.get("rationale", "")
    per_crit_raw = payload.get("per_criterion", {}) or {}
    per_crit: dict[str, float] = {}
    if isinstance(per_crit_raw, dict):
        for cid, entry in per_crit_raw.items():
            if not isinstance(entry, dict):
                continue
            pts = entry.get("points")
            if isinstance(pts, (int, float)):
                per_crit[str(cid)] = float(pts)

    return AggregatedScore(
        total=total,
        max_points=float(rubric.total_points),
        per_criterion=per_crit,
        rationale=str(rationale) if rationale else "",
        judge_trajectories=[raw],
    )


def combine_votes(samples: list[AggregatedScore], max_points: float) -> AggregatedScore:
    """Combine K voting samples into one AggregatedScore.

    Uses the median for totals and per-criterion points (robust to outliers),
    concatenates rationales, and preserves all raw trajectories for audit.
    """
    if not samples:
        return AggregatedScore(
            total=0.0, max_points=max_points, per_criterion={},
            rationale="no_votes", voting_k=0,
        )
    if len(samples) == 1:
        s = samples[0]
        s.voting_k = 1
        return s

    totals = [s.total for s in samples]
    combined_total = float(median(totals))

    keys = set()
    for s in samples:
        keys.update(s.per_criterion.keys())
    combined_per_crit: dict[str, float] = {}
    for k in keys:
        values = [s.per_criterion.get(k, 0.0) for s in samples]
        combined_per_crit[k] = float(median(values))

    trajectories: list[str] = []
    for s in samples:
        trajectories.extend(s.judge_trajectories)

    rationale = " | ".join([s.rationale for s in samples if s.rationale])

    return AggregatedScore(
        total=combined_total,
        max_points=max_points,
        per_criterion=combined_per_crit,
        rationale=rationale,
        judge_trajectories=trajectories,
        voting_k=len(samples),
    )


class ImplicitAggregator:
    """LLM-based rubric aggregator with optional voting@K.

    The Anthropic client is injected so tests can pass a stub; production use
    passes the harness's existing generator client.
    """

    def __init__(
        self,
        client,
        model: str = "claude-sonnet-4-20250514",
        voting_k: int = 1,
        max_tokens: int = 4000,
    ):
        if voting_k not in (1, 3, 5):
            raise ValueError(f"voting_k must be 1, 3, or 5 (got {voting_k})")
        self.client = client
        self.model = model
        self.voting_k = voting_k
        self.max_tokens = max_tokens

    def score(
        self,
        rubric: Rubric,
        attempt: str,
        budget: Optional[BudgetTracker] = None,
    ) -> AggregatedScore:
        """Score an attempt against a rubric with voting@K.

        Returns a best-effort result even on API/parse errors; such failures
        produce an AggregatedScore with total=0 and rationale="parse_error"
        or "api_error".
        """
        prompt = IMPLICIT_JUDGE_USER_TEMPLATE.format(
            task=rubric.task,
            criteria_block=_render_criteria_block(rubric),
            total_points=rubric.total_points,
            pass_threshold=rubric.pass_threshold,
            attempt=attempt,
        )

        samples: list[AggregatedScore] = []
        actual_k = self.voting_k
        # Respect the per-run extra-call budget when provided.
        if budget is not None:
            actual_k = min(self.voting_k, budget.remaining())
            if actual_k <= 0:
                return AggregatedScore(
                    total=0.0,
                    max_points=float(rubric.total_points),
                    per_criterion={},
                    rationale="budget_exceeded",
                    voting_k=0,
                )
        for _ in range(actual_k):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=IMPLICIT_JUDGE_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text if resp.content else ""
            except Exception as e:
                raw = json.dumps({
                    "total": 0.0,
                    "pass_fraction": 0.0,
                    "per_criterion": {},
                    "rationale": f"api_error: {type(e).__name__}",
                })
            samples.append(parse_implicit_verdict(raw, rubric))
            if budget is not None:
                budget.charge(1)

        return combine_votes(samples, max_points=float(rubric.total_points))


def rankings_disagree(
    a_current: AggregatedScore,
    b_current: AggregatedScore,
    a_previous: Optional[AggregatedScore] = None,
    b_previous: Optional[AggregatedScore] = None,
    margin: float = 0.0,
) -> bool:
    """Heuristic divergence check used for telemetry.

    If both ``previous`` snapshots are provided, returns True when the two
    aggregators disagree on whether current > previous (i.e. the sign of the
    improvement flips). Otherwise, returns True when one says percentage is
    above pass_threshold while the other says below.
    """
    def _pct(s: AggregatedScore) -> float:
        return s.percentage if s.max_points > 0 else 0.0

    if a_previous is not None and b_previous is not None:
        a_delta = _pct(a_current) - _pct(a_previous)
        b_delta = _pct(b_current) - _pct(b_previous)
        # Flip in sign beyond the margin
        return (a_delta > margin) != (b_delta > margin)
    # Fallback: absolute-agreement by a coarse pct band (0.1 == 10 pts)
    return abs(_pct(a_current) - _pct(b_current)) > 0.1
