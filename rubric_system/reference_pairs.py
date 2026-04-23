"""
Reference Pair Resolver (Phase 1 — Contrastive Rubric Generation)

Sources contrastive (preferred, rejected) response pairs to ground rubric
generation. Priority order: caller > store > self-contrast > synthetic.

Per the OpenRubrics alignment plan:
  - cap feed to the generator at 3 pairs
  - synthetic pairs are produced in a single generator-model call
  - self-contrast uses N=3 provisional attempts and takes top vs bottom
"""
from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Awaitable

from rubric_system.models import ReferencePair, PairSource


MAX_PAIRS = 3
MIN_PAIRS_DESIRED = 3
SELF_CONTRAST_N = 3


def task_hash(task: str) -> str:
    return hashlib.sha256(task.strip().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Store mining
# ---------------------------------------------------------------------------

def ensure_attempt_column(db_path: Path) -> None:
    """Idempotently add the nullable attempt_text column used for pair mining."""
    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(scored_rubrics)").fetchall()}
        if "attempt_text" not in cols:
            conn.execute("ALTER TABLE scored_rubrics ADD COLUMN attempt_text TEXT")


def mine_pairs_from_store(db_path: Path, task_hash_value: str, k: int = MAX_PAIRS) -> list[ReferencePair]:
    """Mine (preferred, rejected) pairs from RubricStore history on the same task_hash.

    A pair is formed by crossing a ``success`` outcome record (preferred) with a
    ``bug_found`` outcome record (rejected). Both sides must have ``attempt_text``.
    Returns at most ``k`` pairs, ordered by recency of the rejected record.
    """
    if not Path(db_path).exists():
        return []
    ensure_attempt_column(Path(db_path))
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, outcome, attempt_text, created_at
            FROM scored_rubrics
            WHERE task_hash = ?
              AND attempt_text IS NOT NULL
              AND outcome IN ('success', 'bug_found')
            ORDER BY created_at DESC
            """,
            (task_hash_value,),
        ).fetchall()

    preferred = [r for r in rows if r[1] == "success"]
    rejected = [r for r in rows if r[1] == "bug_found"]
    pairs: list[ReferencePair] = []
    for rej in rejected:
        for pref in preferred:
            if pref[0] == rej[0]:
                continue
            pairs.append(ReferencePair(
                preferred=pref[2],
                rejected=rej[2],
                source=PairSource.STORE,
                task_hash=task_hash_value,
                provenance={"preferred_id": pref[0], "rejected_id": rej[0]},
            ))
            if len(pairs) >= k:
                return pairs
    return pairs


# ---------------------------------------------------------------------------
# Self-contrast
# ---------------------------------------------------------------------------

AttemptFn = Callable[[str], Awaitable[str]]       # task -> attempt text
ScoreFn = Callable[[str], Awaitable[float]]       # attempt -> provisional score


async def self_contrast_pair(
    task: str,
    attempt_fn: AttemptFn,
    score_fn: ScoreFn,
    n: int = SELF_CONTRAST_N,
) -> Optional[ReferencePair]:
    """Generate N provisional attempts, score them, return top vs bottom as one pair.

    Returns ``None`` when N < 2 attempts could be produced or when top == bottom.
    """
    if n < 2:
        return None
    attempts: list[str] = []
    for _ in range(n):
        try:
            text = await attempt_fn(task)
        except Exception:
            continue
        if text:
            attempts.append(text)
    if len(attempts) < 2:
        return None
    scored: list[tuple[float, str]] = []
    for text in attempts:
        try:
            s = await score_fn(text)
        except Exception:
            s = 0.0
        scored.append((s, text))
    scored.sort(key=lambda x: x[0])
    worst, best = scored[0], scored[-1]
    if best[1] == worst[1]:
        return None
    return ReferencePair(
        preferred=best[1],
        rejected=worst[1],
        source=PairSource.SELF_CONTRAST,
        task_hash=task_hash(task),
        provenance={"n_attempts": len(attempts), "best_score": best[0], "worst_score": worst[0]},
    )


# ---------------------------------------------------------------------------
# Synthetic pair synthesis
# ---------------------------------------------------------------------------

SYNTHETIC_PAIR_PROMPT = """You are helping build training data for a rubric-based evaluator.

Task:
{task}

Produce exactly 3 contrastive response pairs for this task. Each pair has:
  - "preferred": a strong response that a careful, domain-literate reviewer would accept
  - "rejected":  a plausible but weaker response that would fail review on a concrete, observable dimension

The pairs should differ on different dimensions (do not rehash the same flaw).

Return strictly this JSON and nothing else:
{{
  "pairs": [
    {{"preferred": "...", "rejected": "..."}},
    {{"preferred": "...", "rejected": "..."}},
    {{"preferred": "...", "rejected": "..."}}
  ]
}}"""


def parse_synthetic_pairs(raw: str, task_hash_value: str) -> list[ReferencePair]:
    """Parse the synthetic-pair generator output into ReferencePair objects."""
    text = raw.strip()
    if text.startswith("```"):
        # Tolerate fenced code blocks.
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Attempt to locate the first '{' ... matching '}'.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            payload = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []
    pairs_raw = payload.get("pairs", []) if isinstance(payload, dict) else []
    out: list[ReferencePair] = []
    for p in pairs_raw:
        if not isinstance(p, dict):
            continue
        pref = p.get("preferred")
        rej = p.get("rejected")
        if not isinstance(pref, str) or not isinstance(rej, str):
            continue
        if not pref.strip() or not rej.strip():
            continue
        out.append(ReferencePair(
            preferred=pref,
            rejected=rej,
            source=PairSource.SYNTHETIC,
            task_hash=task_hash_value,
            provenance={"origin": "synthetic_generator"},
        ))
    return out


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

@dataclass
class ReferencePairResolver:
    """Resolve up to MAX_PAIRS reference pairs in priority order."""

    store_db_path: Optional[Path] = None
    attempt_fn: Optional[AttemptFn] = None
    score_fn: Optional[ScoreFn] = None
    synthetic_fn: Optional[Callable[[str], Awaitable[str]]] = None  # task -> raw model text
    min_desired: int = MIN_PAIRS_DESIRED
    max_pairs: int = MAX_PAIRS

    async def resolve(
        self,
        task: str,
        caller_pairs: Optional[list[ReferencePair]] = None,
    ) -> list[ReferencePair]:
        th = task_hash(task)
        collected: list[ReferencePair] = []

        # 1. Caller
        if caller_pairs:
            for p in caller_pairs[: self.max_pairs]:
                if p.source != PairSource.CALLER:
                    p = ReferencePair(
                        preferred=p.preferred,
                        rejected=p.rejected,
                        source=PairSource.CALLER,
                        task_hash=p.task_hash or th,
                        provenance=p.provenance or {"origin": "caller"},
                    )
                collected.append(p)
        if len(collected) >= self.min_desired:
            return collected[: self.max_pairs]

        # 2. Store
        if self.store_db_path is not None:
            remaining = self.max_pairs - len(collected)
            mined = mine_pairs_from_store(self.store_db_path, th, k=remaining)
            collected.extend(mined)
        if len(collected) >= self.min_desired:
            return collected[: self.max_pairs]

        # 3. Self-contrast (one pair)
        if self.attempt_fn is not None and self.score_fn is not None and len(collected) < self.max_pairs:
            sc = await self_contrast_pair(task, self.attempt_fn, self.score_fn)
            if sc is not None:
                collected.append(sc)
        if len(collected) >= self.min_desired:
            return collected[: self.max_pairs]

        # 4. Synthetic
        if self.synthetic_fn is not None and len(collected) < self.max_pairs:
            try:
                raw = await self.synthetic_fn(task)
            except Exception:
                raw = ""
            if raw:
                synth = parse_synthetic_pairs(raw, th)
                remaining = self.max_pairs - len(collected)
                collected.extend(synth[:remaining])

        return collected[: self.max_pairs]


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def render_pair_block(pairs: list[ReferencePair]) -> str:
    """Render pairs into the optional block appended to RUBRIC_GENERATION_PROMPT.

    When no pairs are supplied, returns an empty string so the prompt is
    byte-identical to the pre-Phase-1 template.
    """
    if not pairs:
        return ""
    lines = [
        "",
        "## Reference pairs (up to 3 — real outcomes from past runs, caller input, or synthesized contrasts)",
        "For each pair, the PREFERRED response is better than the REJECTED response for this task.",
        "",
        "Before writing criteria, you MUST:",
        "  (a) Extract 3–8 `discriminators` — concrete, observable differences that make",
        "      PREFERRED better than REJECTED. Each discriminator must be a short noun phrase.",
        "  (b) In the rubric JSON, emit a top-level `discriminators: [str, ...]` field listing them.",
        "  (c) Every criterion you emit must include a `cited_discriminators: [slug, ...]` field",
        "      citing at least one discriminator by exact string match.",
        "",
    ]
    for i, p in enumerate(pairs, start=1):
        src = p.source.value if hasattr(p.source, "value") else str(p.source)
        lines.append(f"### Pair {i} [source: {src}]")
        lines.append("PREFERRED:")
        lines.append(p.preferred)
        lines.append("")
        lines.append("REJECTED:")
        lines.append(p.rejected)
        lines.append("")
    return "\n".join(lines)
