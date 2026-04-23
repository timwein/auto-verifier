"""
Unit tests for Phase 4 — implicit LLM-judge aggregator + voting@K.
"""
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from rubric_system.models import (
    Rubric, Criterion, ScoringRubric, ScoringMethod,
)
from rubric_system.aggregation import (
    ImplicitAggregator,
    AggregatedScore,
    BudgetTracker,
    parse_implicit_verdict,
    combine_votes,
    rankings_disagree,
    IMPLICIT_JUDGE_USER_TEMPLATE,
)


def _rubric(max_pts_per_crit: int = 5, n_criteria: int = 2) -> Rubric:
    criteria = [
        Criterion(
            id=f"c{i}", category="cat", description=f"desc {i}", pass_condition="",
            scoring=ScoringRubric(method=ScoringMethod.WEIGHTED_COMPONENTS, max_points=max_pts_per_crit),
        )
        for i in range(n_criteria)
    ]
    total = max_pts_per_crit * n_criteria
    return Rubric(task="T", domain="d", criteria=criteria, total_points=total, pass_threshold=0.8)


class _StubClient:
    """Minimal stub matching the subset of anthropic.Anthropic we use."""

    def __init__(self, responses: list[str]):
        self._queue = list(responses)
        self._calls = 0

        # Build the nested .messages.create interface.
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self._calls += 1
        if not self._queue:
            raise RuntimeError("no responses queued")
        payload = self._queue.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(text=payload)])


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def test_parse_clean_json():
    r = _rubric()
    raw = json.dumps({
        "total": 8.0,
        "pass_fraction": 0.8,
        "per_criterion": {
            "c0": {"points": 4.0, "max_points": 5, "note": "ok"},
            "c1": {"points": 4.0, "max_points": 5, "note": "ok"},
        },
        "rationale": "solid on both criteria",
    })
    score = parse_implicit_verdict(raw, r)
    assert score.total == 8.0
    assert score.per_criterion == {"c0": 4.0, "c1": 4.0}
    assert "solid" in score.rationale


def test_parse_tolerates_fence():
    r = _rubric()
    raw = "```json\n" + json.dumps({"total": 5, "per_criterion": {}, "rationale": "x"}) + "\n```"
    score = parse_implicit_verdict(raw, r)
    assert score.total == 5.0


def test_parse_returns_zero_on_garbage():
    r = _rubric()
    score = parse_implicit_verdict("not json", r)
    assert score.total == 0.0
    assert score.rationale == "parse_error"


def test_parse_skips_malformed_per_criterion_entries():
    r = _rubric()
    raw = json.dumps({
        "total": 3,
        "per_criterion": {
            "c0": {"points": 2},
            "c1": "bad entry",
            "c2": {"no_points": True},
        },
        "rationale": "",
    })
    score = parse_implicit_verdict(raw, r)
    assert score.per_criterion == {"c0": 2.0}


# ---------------------------------------------------------------------------
# Voting combination
# ---------------------------------------------------------------------------

def test_combine_votes_uses_median_for_totals():
    samples = [
        AggregatedScore(total=2.0, max_points=10, per_criterion={"c0": 1.0}),
        AggregatedScore(total=8.0, max_points=10, per_criterion={"c0": 4.0}),
        AggregatedScore(total=5.0, max_points=10, per_criterion={"c0": 3.0}),
    ]
    combined = combine_votes(samples, max_points=10)
    assert combined.total == 5.0  # median of 2, 5, 8
    assert combined.per_criterion == {"c0": 3.0}
    assert combined.voting_k == 3


def test_combine_votes_single_sample_marks_k1():
    s = AggregatedScore(total=4.0, max_points=5, per_criterion={"c0": 4.0})
    combined = combine_votes([s], max_points=5)
    assert combined.voting_k == 1
    assert combined.total == 4.0


def test_combine_votes_empty_returns_zero():
    combined = combine_votes([], max_points=10)
    assert combined.total == 0.0
    assert combined.voting_k == 0


# ---------------------------------------------------------------------------
# ImplicitAggregator.score + budget
# ---------------------------------------------------------------------------

def test_score_single_vote_calls_once():
    r = _rubric()
    responses = [json.dumps({"total": 7.5, "per_criterion": {"c0": 4.0, "c1": 3.5}, "rationale": "ok"})]
    client = _StubClient(responses)
    agg = ImplicitAggregator(client=client, voting_k=1)
    score = agg.score(r, "some attempt")
    assert score.total == 7.5
    assert client._calls == 1
    assert score.voting_k == 1


def test_score_voting_at_three_produces_median():
    r = _rubric()
    responses = [
        json.dumps({"total": 2, "per_criterion": {}, "rationale": ""}),
        json.dumps({"total": 9, "per_criterion": {}, "rationale": ""}),
        json.dumps({"total": 6, "per_criterion": {}, "rationale": ""}),
    ]
    client = _StubClient(responses)
    agg = ImplicitAggregator(client=client, voting_k=3)
    score = agg.score(r, "attempt")
    assert score.total == 6.0
    assert score.voting_k == 3
    assert client._calls == 3


def test_score_respects_budget_tracker():
    r = _rubric()
    responses = [
        json.dumps({"total": 5, "per_criterion": {}, "rationale": ""}),
        json.dumps({"total": 6, "per_criterion": {}, "rationale": ""}),
        json.dumps({"total": 7, "per_criterion": {}, "rationale": ""}),
    ]
    client = _StubClient(responses)
    budget = BudgetTracker(limit=2)
    agg = ImplicitAggregator(client=client, voting_k=3)
    score = agg.score(r, "attempt", budget=budget)
    # Budget caps voting_k at 2, so only 2 calls happen.
    assert client._calls == 2
    assert budget.used == 2
    assert score.voting_k == 2


def test_score_budget_exhausted_returns_placeholder():
    r = _rubric()
    client = _StubClient([])
    budget = BudgetTracker(limit=0)
    agg = ImplicitAggregator(client=client, voting_k=3)
    score = agg.score(r, "attempt", budget=budget)
    assert client._calls == 0
    assert score.rationale == "budget_exceeded"
    assert score.voting_k == 0


def test_score_api_error_returns_zero_without_crashing():
    r = _rubric()
    agg = ImplicitAggregator(client=_StubClient([]), voting_k=1)
    # Queue is empty → _StubClient raises on messages.create → caught by ImplicitAggregator
    score = agg.score(r, "attempt")
    assert score.total == 0.0
    assert "api_error" in score.rationale


def test_invalid_voting_k_raises():
    with pytest.raises(ValueError):
        ImplicitAggregator(client=_StubClient([]), voting_k=2)


# ---------------------------------------------------------------------------
# rankings_disagree
# ---------------------------------------------------------------------------

def test_rankings_disagree_when_deltas_flip():
    a_prev = AggregatedScore(total=5, max_points=10, per_criterion={})
    a_curr = AggregatedScore(total=8, max_points=10, per_criterion={})   # +
    b_prev = AggregatedScore(total=5, max_points=10, per_criterion={})
    b_curr = AggregatedScore(total=3, max_points=10, per_criterion={})   # −
    assert rankings_disagree(a_curr, b_curr, a_prev, b_prev) is True


def test_rankings_agree_when_deltas_align():
    a_prev = AggregatedScore(total=5, max_points=10, per_criterion={})
    a_curr = AggregatedScore(total=8, max_points=10, per_criterion={})
    b_prev = AggregatedScore(total=4, max_points=10, per_criterion={})
    b_curr = AggregatedScore(total=9, max_points=10, per_criterion={})
    assert rankings_disagree(a_curr, b_curr, a_prev, b_prev) is False


def test_rankings_fallback_uses_absolute_gap_when_no_history():
    a = AggregatedScore(total=9, max_points=10, per_criterion={})
    b = AggregatedScore(total=7, max_points=10, per_criterion={})
    # |0.9 - 0.7| = 0.2 > 0.1 → disagree
    assert rankings_disagree(a, b) is True
    c = AggregatedScore(total=8, max_points=10, per_criterion={})
    # |0.9 - 0.8| = 0.1 (not strictly greater) → agree
    assert rankings_disagree(a, c) is False


# ---------------------------------------------------------------------------
# Prompt contract
# ---------------------------------------------------------------------------

def test_user_template_includes_key_fields():
    r = _rubric()
    rendered = IMPLICIT_JUDGE_USER_TEMPLATE.format(
        task="T",
        criteria_block="  - c0 — desc 0 — 5pts\n  - c1 — desc 1 — 5pts",
        total_points=r.total_points,
        pass_threshold=r.pass_threshold,
        attempt="my response",
    )
    assert "RUBRIC CRITERIA" in rendered
    assert "CANDIDATE RESPONSE" in rendered
    assert "my response" in rendered
    assert "10" in rendered  # total_points


# ---------------------------------------------------------------------------
# BudgetTracker
# ---------------------------------------------------------------------------

def test_budget_would_exceed_reflects_remaining():
    b = BudgetTracker(limit=5)
    assert b.would_exceed(5) is False
    b.charge(3)
    assert b.would_exceed(3) is True
    assert b.remaining() == 2
