"""
Unit tests for Phase 2 — hard-rule / principle taxonomy.
"""
from rubric_system.models import (
    CriterionTier,
    ScoringMethod,
    ScoringRubric,
    Criterion,
    Rubric,
    infer_tier,
)
from rubric_system.tier_gate import (
    evaluate_tier_coverage,
    backfill_tiers,
    tier_of,
    build_regeneration_feedback,
    HARD_RULE_MIN,
    PRINCIPLE_MIN,
)


def _crit(cid: str, method: ScoringMethod, tier=None) -> Criterion:
    return Criterion(
        id=cid, category="cat", description="d", pass_condition="",
        scoring=ScoringRubric(method=method, max_points=3),
        tier=tier,
    )


# ---------------------------------------------------------------------------
# infer_tier default mapping
# ---------------------------------------------------------------------------

def test_infer_tier_maps_binary_and_penalty_to_hard_rule():
    assert infer_tier(ScoringMethod.BINARY) is CriterionTier.HARD_RULE
    assert infer_tier(ScoringMethod.PENALTY_BASED) is CriterionTier.HARD_RULE


def test_infer_tier_maps_graded_methods_to_principle():
    for m in (
        ScoringMethod.PERCENTAGE,
        ScoringMethod.WEIGHTED_COMPONENTS,
        ScoringMethod.THRESHOLD_TIERS,
        ScoringMethod.COUNT_BASED,
    ):
        assert infer_tier(m) is CriterionTier.PRINCIPLE


def test_tier_of_uses_explicit_over_inference():
    c = _crit("x", ScoringMethod.BINARY, tier=CriterionTier.PRINCIPLE)
    # Explicit declaration wins over the default mapping
    assert tier_of(c) is CriterionTier.PRINCIPLE


def test_tier_of_falls_back_to_inference_when_unset():
    c = _crit("x", ScoringMethod.PENALTY_BASED, tier=None)
    assert tier_of(c) is CriterionTier.HARD_RULE


# ---------------------------------------------------------------------------
# Coverage evaluation
# ---------------------------------------------------------------------------

def test_coverage_passes_with_min_both_tiers():
    criteria = [
        _crit("h1", ScoringMethod.BINARY, tier=CriterionTier.HARD_RULE),
        _crit("h2", ScoringMethod.PENALTY_BASED, tier=CriterionTier.HARD_RULE),
        _crit("p1", ScoringMethod.WEIGHTED_COMPONENTS, tier=CriterionTier.PRINCIPLE),
        _crit("p2", ScoringMethod.THRESHOLD_TIERS, tier=CriterionTier.PRINCIPLE),
        _crit("p3", ScoringMethod.COUNT_BASED, tier=CriterionTier.PRINCIPLE),
    ]
    r = Rubric(task="t", domain="d", criteria=criteria)
    report = evaluate_tier_coverage(r)
    assert report.passed is True
    assert report.hard_rules == HARD_RULE_MIN
    assert report.principles == PRINCIPLE_MIN
    assert report.needs_hard_rules == 0
    assert report.needs_principles == 0


def test_coverage_fails_when_missing_hard_rules():
    criteria = [
        _crit("h1", ScoringMethod.BINARY, tier=CriterionTier.HARD_RULE),
        _crit("p1", ScoringMethod.WEIGHTED_COMPONENTS, tier=CriterionTier.PRINCIPLE),
        _crit("p2", ScoringMethod.THRESHOLD_TIERS, tier=CriterionTier.PRINCIPLE),
        _crit("p3", ScoringMethod.COUNT_BASED, tier=CriterionTier.PRINCIPLE),
    ]
    report = evaluate_tier_coverage(Rubric(task="t", domain="d", criteria=criteria))
    assert report.passed is False
    assert report.needs_hard_rules == 1
    assert report.needs_principles == 0


def test_coverage_fails_when_all_one_tier():
    criteria = [_crit(f"p{i}", ScoringMethod.WEIGHTED_COMPONENTS, tier=CriterionTier.PRINCIPLE) for i in range(5)]
    report = evaluate_tier_coverage(Rubric(task="t", domain="d", criteria=criteria))
    assert report.passed is False
    assert report.hard_rules == 0
    assert report.needs_hard_rules == HARD_RULE_MIN
    assert report.needs_principles == 0


def test_coverage_counts_untyped_criteria_via_inference():
    # Untyped criterion with BINARY scoring still counts as a hard rule via infer_tier.
    criteria = [
        _crit("h1", ScoringMethod.BINARY, tier=None),
        _crit("h2", ScoringMethod.PENALTY_BASED, tier=None),
        _crit("p1", ScoringMethod.WEIGHTED_COMPONENTS, tier=None),
        _crit("p2", ScoringMethod.THRESHOLD_TIERS, tier=None),
        _crit("p3", ScoringMethod.COUNT_BASED, tier=None),
    ]
    report = evaluate_tier_coverage(Rubric(task="t", domain="d", criteria=criteria))
    assert report.hard_rules == 2
    assert report.principles == 3
    assert report.untyped == 5
    assert report.passed is True


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def test_backfill_tiers_sets_tier_on_untyped_criteria():
    criteria = [
        _crit("a", ScoringMethod.BINARY, tier=None),
        _crit("b", ScoringMethod.WEIGHTED_COMPONENTS, tier=None),
    ]
    r = Rubric(task="t", domain="d", criteria=criteria)
    backfill_tiers(r)
    assert r.criteria[0].tier is CriterionTier.HARD_RULE
    assert r.criteria[1].tier is CriterionTier.PRINCIPLE


def test_backfill_preserves_explicit_tier():
    # A BINARY criterion explicitly declared as a principle stays a principle.
    c = _crit("x", ScoringMethod.BINARY, tier=CriterionTier.PRINCIPLE)
    r = Rubric(task="t", domain="d", criteria=[c])
    backfill_tiers(r)
    assert r.criteria[0].tier is CriterionTier.PRINCIPLE


# ---------------------------------------------------------------------------
# Feedback rendering
# ---------------------------------------------------------------------------

def test_feedback_mentions_needed_counts():
    r = evaluate_tier_coverage(Rubric(task="t", domain="d", criteria=[]))
    fb = build_regeneration_feedback(r)
    assert f"{HARD_RULE_MIN} additional hard_rule" in fb
    assert f"{PRINCIPLE_MIN} additional principle" in fb


def test_feedback_omits_tier_when_satisfied():
    criteria = [_crit(f"h{i}", ScoringMethod.PENALTY_BASED, tier=CriterionTier.HARD_RULE) for i in range(HARD_RULE_MIN)]
    criteria += [_crit(f"p{i}", ScoringMethod.WEIGHTED_COMPONENTS, tier=CriterionTier.PRINCIPLE) for i in range(PRINCIPLE_MIN)]
    report = evaluate_tier_coverage(Rubric(task="t", domain="d", criteria=criteria))
    fb = build_regeneration_feedback(report)
    assert "additional hard_rule" not in fb
    assert "additional principle" not in fb
