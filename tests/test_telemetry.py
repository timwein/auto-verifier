"""
Unit tests for cross-cutting per-run telemetry writer.
"""
import json
from pathlib import Path

import pytest

from rubric_system.telemetry import (
    write_run_telemetry,
    summarize_runs,
    telemetry_path,
)


def test_write_creates_file_and_appends(tmp_path: Path):
    p = tmp_path / "runs.jsonl"
    write_run_telemetry({"run_id": "a", "final_percentage": 0.9}, path=p)
    write_run_telemetry({"run_id": "b", "final_percentage": 0.7}, path=p)
    lines = p.read_text().strip().split("\n")
    assert len(lines) == 2
    a = json.loads(lines[0])
    b = json.loads(lines[1])
    assert a["run_id"] == "a"
    assert b["run_id"] == "b"
    # created_at auto-filled when missing
    assert "created_at" in a


def test_write_survives_unserializable_values(tmp_path: Path):
    p = tmp_path / "runs.jsonl"
    class Weird:
        def __repr__(self):
            return "<Weird>"

    write_run_telemetry({"run_id": "x", "weird": Weird()}, path=p)
    raw = p.read_text().strip()
    parsed = json.loads(raw)
    # Non-JSON value fell back to repr via default=str
    assert parsed["weird"] == "<Weird>"


def test_summarize_counts_and_aggregates(tmp_path: Path):
    p = tmp_path / "runs.jsonl"
    for i in range(3):
        write_run_telemetry({
            "run_id": f"r{i}",
            "consistency_hit_rate": 0.7 + 0.1 * i,
            "aggregator_disagreements": i,
            "dataset_record_saved": i == 0,
            "phase_flags": {"phase1": True, "phase3": (i % 2 == 0)},
        }, path=p)

    s = summarize_runs(path=p)
    assert s["count"] == 3
    # median of 0.7, 0.8, 0.9 is 0.8
    assert s["median_consistency_hit_rate"] == pytest.approx(0.8)
    assert s["aggregator_disagreements_total"] == 0 + 1 + 2
    assert s["dataset_saves"] == 1
    assert s["phase_flags_on"]["phase1"] == 3
    assert s["phase_flags_on"]["phase3"] == 2


def test_summarize_handles_missing_file(tmp_path: Path):
    p = tmp_path / "nope.jsonl"
    s = summarize_runs(path=p)
    assert s == {"count": 0}


def test_summarize_ignores_malformed_lines(tmp_path: Path):
    p = tmp_path / "runs.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"run_id": "ok"}\nnot json\n{"run_id":"also_ok"}\n')
    s = summarize_runs(path=p)
    assert s["count"] == 2


def test_telemetry_path_in_auto_verifier_data_dir():
    # Sanity: default path lives under the expected data dir
    p = telemetry_path()
    assert ".auto-verifier-data" in str(p)
    assert p.name == "runs.jsonl"
