"""
Unit tests for Phase 1 — Contrastive Rubric Generation.
"""
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from rubric_system.models import ReferencePair, PairSource, Rubric, Criterion, ScoringRubric, ScoringMethod
from rubric_system.reference_pairs import (
    ReferencePairResolver,
    SYNTHETIC_PAIR_PROMPT,
    parse_synthetic_pairs,
    mine_pairs_from_store,
    ensure_attempt_column,
    render_pair_block,
    self_contrast_pair,
    task_hash,
)


# ---------------------------------------------------------------------------
# Model additions
# ---------------------------------------------------------------------------

def test_reference_pair_dataclass_roundtrip():
    p = ReferencePair(preferred="good", rejected="bad", source=PairSource.CALLER)
    assert p.preferred == "good"
    assert p.rejected == "bad"
    assert p.source is PairSource.CALLER


def test_rubric_has_discriminators_default_empty():
    r = Rubric(task="t", domain="d", criteria=[])
    assert r.discriminators == []
    assert r.consistency_hit_rate is None


def test_criterion_cited_discriminators_default_empty():
    c = Criterion(
        id="x", category="c", description="d", pass_condition="",
        scoring=ScoringRubric(method=ScoringMethod.BINARY, max_points=3),
    )
    assert c.cited_discriminators == []


# ---------------------------------------------------------------------------
# Synthetic pair parser
# ---------------------------------------------------------------------------

def test_parse_synthetic_pairs_clean_json():
    raw = json.dumps({
        "pairs": [
            {"preferred": "A", "rejected": "B"},
            {"preferred": "C", "rejected": "D"},
        ]
    })
    pairs = parse_synthetic_pairs(raw, task_hash_value="abc")
    assert len(pairs) == 2
    assert all(p.source is PairSource.SYNTHETIC for p in pairs)
    assert pairs[0].preferred == "A" and pairs[0].rejected == "B"


def test_parse_synthetic_pairs_tolerates_code_fence():
    raw = "```json\n" + json.dumps({"pairs": [{"preferred": "x", "rejected": "y"}]}) + "\n```"
    pairs = parse_synthetic_pairs(raw, task_hash_value="abc")
    assert len(pairs) == 1


def test_parse_synthetic_pairs_tolerates_prose_wrapper():
    raw = "Here are the pairs:\n" + json.dumps({"pairs": [{"preferred": "x", "rejected": "y"}]}) + "\nEnd."
    pairs = parse_synthetic_pairs(raw, task_hash_value="abc")
    assert len(pairs) == 1


def test_parse_synthetic_pairs_skips_malformed():
    raw = json.dumps({"pairs": [
        {"preferred": "ok", "rejected": "also ok"},
        {"preferred": 42, "rejected": "bad type"},   # preferred not str
        {"preferred": "   ", "rejected": "empty"},   # empty preferred
        {},                                           # missing keys
    ]})
    pairs = parse_synthetic_pairs(raw, task_hash_value="abc")
    assert len(pairs) == 1


def test_parse_synthetic_pairs_returns_empty_on_garbage():
    assert parse_synthetic_pairs("not json at all", task_hash_value="abc") == []


# ---------------------------------------------------------------------------
# Store mining
# ---------------------------------------------------------------------------

def _seed_store(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE scored_rubrics (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                task_hash TEXT NOT NULL,
                template_id TEXT,
                criteria JSON NOT NULL,
                scores JSON NOT NULL,
                overall_score REAL NOT NULL,
                outcome TEXT,
                outcome_details TEXT,
                days_to_bug INTEGER,
                created_at TEXT NOT NULL,
                project TEXT,
                author TEXT,
                iteration_count INTEGER NOT NULL
            );
        """)


def test_mine_pairs_from_store_cross_joins_success_and_bug():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rubrics.db"
        _seed_store(db)
        th = task_hash("my task")
        ensure_attempt_column(db)
        with sqlite3.connect(db) as conn:
            conn.execute("""
                INSERT INTO scored_rubrics
                (id, task, task_hash, template_id, criteria, scores, overall_score,
                 outcome, outcome_details, days_to_bug, created_at, project, author, iteration_count)
                VALUES ('r1','t', ?, NULL, '[]', '[]', 0.9, 'success', NULL, NULL, '2026-01-01',NULL,NULL,1)
            """, (th,))
            conn.execute("""
                INSERT INTO scored_rubrics
                (id, task, task_hash, template_id, criteria, scores, overall_score,
                 outcome, outcome_details, days_to_bug, created_at, project, author, iteration_count)
                VALUES ('r2','t', ?, NULL, '[]', '[]', 0.3, 'bug_found', NULL, NULL, '2026-01-02',NULL,NULL,1)
            """, (th,))
            conn.execute("UPDATE scored_rubrics SET attempt_text = 'BEST' WHERE id='r1'")
            conn.execute("UPDATE scored_rubrics SET attempt_text = 'BUG'  WHERE id='r2'")
        pairs = mine_pairs_from_store(db, th, k=3)
        assert len(pairs) == 1
        assert pairs[0].preferred == "BEST"
        assert pairs[0].rejected == "BUG"
        assert pairs[0].source is PairSource.STORE


def test_mine_pairs_skips_rows_without_attempt_text():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rubrics.db"
        _seed_store(db)
        th = task_hash("my task")
        ensure_attempt_column(db)
        with sqlite3.connect(db) as conn:
            conn.execute("""
                INSERT INTO scored_rubrics
                (id, task, task_hash, template_id, criteria, scores, overall_score,
                 outcome, outcome_details, days_to_bug, created_at, project, author, iteration_count)
                VALUES ('r1','t', ?, NULL, '[]', '[]', 0.9, 'success', NULL, NULL, '2026-01-01',NULL,NULL,1)
            """, (th,))
            conn.execute("""
                INSERT INTO scored_rubrics
                (id, task, task_hash, template_id, criteria, scores, overall_score,
                 outcome, outcome_details, days_to_bug, created_at, project, author, iteration_count)
                VALUES ('r2','t', ?, NULL, '[]', '[]', 0.3, 'bug_found', NULL, NULL, '2026-01-02',NULL,NULL,1)
            """, (th,))
            # no attempt_text populated
        assert mine_pairs_from_store(db, th, k=3) == []


def test_mine_pairs_returns_empty_when_db_missing():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "does-not-exist.db"
        assert mine_pairs_from_store(missing, task_hash("x"), k=3) == []


# ---------------------------------------------------------------------------
# Self-contrast
# ---------------------------------------------------------------------------

def test_self_contrast_pair_returns_top_vs_bottom():
    attempts = iter(["low-quality answer", "medium answer", "high-quality answer"])

    async def _run():
        async def attempt_fn(task):
            return next(attempts)

        scores = {"low-quality answer": 0.1, "medium answer": 0.5, "high-quality answer": 0.9}

        async def score_fn(text):
            return scores[text]

        return await self_contrast_pair("task", attempt_fn, score_fn, n=3)

    pair = asyncio.run(_run())
    assert pair is not None
    assert pair.preferred == "high-quality answer"
    assert pair.rejected == "low-quality answer"
    assert pair.source is PairSource.SELF_CONTRAST


def test_self_contrast_pair_returns_none_when_single_attempt():
    async def _run():
        async def attempt_fn(task):
            return "only one"

        async def score_fn(text):
            return 0.5

        return await self_contrast_pair("task", attempt_fn, score_fn, n=1)

    assert asyncio.run(_run()) is None


# ---------------------------------------------------------------------------
# Resolver priority
# ---------------------------------------------------------------------------

def test_resolver_prioritizes_caller_over_all_sources():
    caller = [ReferencePair(preferred="caller-pref", rejected="caller-rej", source=PairSource.CALLER)]

    async def _run():
        synth_called = {"count": 0}

        async def synth_fn(task):
            synth_called["count"] += 1
            return json.dumps({"pairs": [{"preferred": "s", "rejected": "s2"}] * 3})

        resolver = ReferencePairResolver(
            store_db_path=None,
            attempt_fn=None,
            score_fn=None,
            synthetic_fn=synth_fn,
            min_desired=3,  # 1 caller pair < 3 → would normally fall through
            max_pairs=3,
        )
        # Caller supplied only 1, so resolver will still fall through to synthetic
        # to top up. That's expected. Test that caller pair is preserved as first.
        resolved = await resolver.resolve("task", caller_pairs=caller)
        return resolved, synth_called["count"]

    resolved, synth_calls = asyncio.run(_run())
    assert len(resolved) >= 1
    assert resolved[0].preferred == "caller-pref"
    assert resolved[0].source is PairSource.CALLER


def test_resolver_returns_early_when_caller_supplies_enough():
    caller = [
        ReferencePair(preferred=f"p{i}", rejected=f"r{i}", source=PairSource.CALLER)
        for i in range(3)
    ]

    async def _run():
        synth_called = {"count": 0}

        async def synth_fn(task):
            synth_called["count"] += 1
            return ""

        resolver = ReferencePairResolver(
            store_db_path=None, attempt_fn=None, score_fn=None,
            synthetic_fn=synth_fn, min_desired=3, max_pairs=3,
        )
        pairs = await resolver.resolve("task", caller_pairs=caller)
        return pairs, synth_called["count"]

    pairs, calls = asyncio.run(_run())
    assert len(pairs) == 3
    assert calls == 0, "synthetic fn must not be called when caller supplies enough"


def test_resolver_caps_at_max_pairs():
    caller = [
        ReferencePair(preferred=f"p{i}", rejected=f"r{i}", source=PairSource.CALLER)
        for i in range(10)
    ]

    async def _run():
        resolver = ReferencePairResolver(max_pairs=3)
        return await resolver.resolve("task", caller_pairs=caller)

    assert len(asyncio.run(_run())) == 3


# ---------------------------------------------------------------------------
# Pair block rendering
# ---------------------------------------------------------------------------

def test_render_pair_block_empty_returns_empty_string():
    assert render_pair_block([]) == ""


def test_render_pair_block_nonempty_includes_both_responses():
    pairs = [ReferencePair(preferred="P1", rejected="R1", source=PairSource.CALLER)]
    block = render_pair_block(pairs)
    assert "P1" in block
    assert "R1" in block
    assert "discriminators" in block
    assert "caller" in block


# ---------------------------------------------------------------------------
# Synthetic prompt contract
# ---------------------------------------------------------------------------

def test_synthetic_prompt_requests_exactly_3_pairs():
    rendered = SYNTHETIC_PAIR_PROMPT.format(task="Example task")
    assert "exactly 3" in rendered
    assert "Example task" in rendered
