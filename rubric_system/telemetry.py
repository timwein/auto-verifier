"""
Per-run telemetry writer (cross-cutting, OpenRubrics alignment).

Appends one JSONL record per run to
``~/.auto-verifier-data/telemetry/runs.jsonl``. Consumed by ``self_improve.py``
and by any post-hoc analysis that wants to compare pre/post-phase behavior
during the soak period.

Schema (all fields optional; missing fields are simply absent):
  run_id                         str
  task_hash                      str
  created_at                     ISO8601
  phase_flags                    dict[str, bool]
  pairs_used                     int
  pairs_source                   list[str]
  discriminators_count           int
  tier_counts                    dict[str, int]
  tier_regenerations             int
  consistency_hit_rate           float
  consistency_n_pairs            int
  consistency_status             str
  consistency_retries            int
  aggregator_disagreements       int
  voting_k                       int
  extra_calls                    int
  extra_calls_budget_exceeded    bool
  dataset_record_saved           bool
  dataset_total_records          int
  rubric_id                      str
  final_percentage               float
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def telemetry_path() -> Path:
    return Path.home() / ".auto-verifier-data" / "telemetry" / "runs.jsonl"


def write_run_telemetry(record: dict[str, Any], path: Path | None = None) -> Path:
    """Append a telemetry record to the runs JSONL file.

    Failures are swallowed — telemetry must never break a run.
    Returns the path written to (or an unusable path on error).
    """
    p = path or telemetry_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        record = dict(record)
        record.setdefault("created_at", datetime.utcnow().isoformat())
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass
    return p


def summarize_runs(path: Path | None = None) -> dict[str, Any]:
    """Small convenience summary used by ad-hoc scripts / tests.

    Returns counts keyed by phase_flag and a few aggregate stats. Safe to call
    when the telemetry file does not yet exist.
    """
    p = path or telemetry_path()
    if not p.exists():
        return {"count": 0}

    count = 0
    hit_rates: list[float] = []
    disagreement_total = 0
    dataset_saves = 0
    flag_counts: dict[str, int] = {}
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                count += 1
                if isinstance(rec.get("consistency_hit_rate"), (int, float)):
                    hit_rates.append(float(rec["consistency_hit_rate"]))
                disagreement_total += int(rec.get("aggregator_disagreements", 0) or 0)
                if rec.get("dataset_record_saved"):
                    dataset_saves += 1
                for flag, on in (rec.get("phase_flags") or {}).items():
                    if on:
                        flag_counts[flag] = flag_counts.get(flag, 0) + 1
    except Exception:
        return {"count": count}

    summary = {
        "count": count,
        "median_consistency_hit_rate": _median(hit_rates),
        "aggregator_disagreements_total": disagreement_total,
        "dataset_saves": dataset_saves,
        "phase_flags_on": flag_counts,
    }
    return summary


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])
