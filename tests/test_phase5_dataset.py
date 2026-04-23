"""
Unit tests for Phase 5 — dataset scaffolding + privacy scrubber.
"""
import tempfile
from pathlib import Path

import pytest

from rubric_system.privacy import scrub
from rubric_system.rubric_learning import RubricStore


# ---------------------------------------------------------------------------
# Privacy scrubber patterns
# ---------------------------------------------------------------------------

def test_scrub_email():
    out = scrub("Contact me at alice@example.com thanks")
    assert "alice@example.com" not in out
    assert "[REDACTED_EMAIL]" in out


def test_scrub_preserves_text_when_clean():
    text = "This is a normal sentence with no secrets."
    assert scrub(text) == text


def test_scrub_anthropic_api_key():
    out = scrub("key=sk-ant-abcdefghijklmnopqrstuvwxyz1234567890 more text")
    assert "sk-ant-abcdefghijk" not in out
    assert "[REDACTED_ANTHROPIC_KEY]" in out


def test_scrub_openai_api_key():
    out = scrub("my sk-ABCDEFGHIJKLMNOPQRSTUVWX ya")
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in out
    assert "[REDACTED_OPENAI_KEY]" in out


def test_scrub_github_token():
    out = scrub("token = ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaa more")
    assert "ghp_" not in out or "[REDACTED" in out


def test_scrub_aws_access_key():
    out = scrub("aws id AKIAIOSFODNN7EXAMPLE here")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED_AWS_KEY]" in out


def test_scrub_bearer_header():
    out = scrub("Authorization: Bearer abc123def456ghi789xyzABC==")
    assert "abc123def456ghi789xyzABC==" not in out


def test_scrub_url_with_credentials():
    out = scrub("connect to https://user:secretpass@example.com/api now")
    assert "user:secretpass@" not in out
    assert "[REDACTED_CRED]" in out


def test_scrub_url_with_api_key_param():
    out = scrub("fetch https://api.example.com/x?api_key=abc123xyz&foo=bar ok")
    assert "api_key=abc123xyz" not in out
    assert "[REDACTED_TOKEN]" in out
    # non-secret query param should survive
    assert "foo=bar" in out


def test_scrub_pem_block():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA..blah..blah..\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = scrub(f"some prefix\n{pem}\nsome suffix")
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "[REDACTED_PRIVATE_KEY_BLOCK]" in out


def test_scrub_length_is_monotonic_non_increasing():
    # For every pattern, replacement must not be longer than the match — else
    # downstream storage assumptions break.
    samples = [
        "user@example.com",
        "sk-ant-" + "a" * 40,
        "https://api/x?token=xxxxxxxxxxxxxxxxxxxxxxxx&k=v",
        "Authorization: Bearer " + "X" * 30,
        "AKIAIOSFODNN7EXAMPLE",
    ]
    for s in samples:
        assert len(scrub(s)) <= len(s), f"scrub grew the string for input: {s}"


def test_scrub_handles_none_and_empty_gracefully():
    assert scrub("") == ""
    assert scrub(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RubricStore dataset table
# ---------------------------------------------------------------------------

def test_save_and_count_dataset_records(tmp_path: Path):
    store = RubricStore(db_path=str(tmp_path / "rubrics.db"))
    assert store.count_dataset_records() == 0
    rid = store.save_dataset_record(
        task_text="Write a brief summary",
        preferred="strong answer",
        rejected="weak answer",
        rubric_json='{"criteria": []}',
        rubric_consistency_hit_rate=0.9,
        rubric_tier_counts='{"hard_rule": 2, "principle": 3}',
        pair_sources="caller,synthetic",
        synthetic_fallback_used=True,
        source_run_id="run_abc",
    )
    assert rid > 0
    assert store.count_dataset_records() == 1


def test_dataset_record_survives_reconnect(tmp_path: Path):
    db = str(tmp_path / "rubrics.db")
    s1 = RubricStore(db_path=db)
    s1.save_dataset_record(
        task_text="task", preferred="p", rejected="r", rubric_json="{}",
    )
    s2 = RubricStore(db_path=db)
    assert s2.count_dataset_records() == 1


def test_dataset_table_schema_has_expected_columns(tmp_path: Path):
    import sqlite3
    store = RubricStore(db_path=str(tmp_path / "rubrics.db"))
    with sqlite3.connect(store.db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(rubric_dataset)").fetchall()}
    expected = {
        "id", "created_at", "task_hash", "task_text", "preferred", "rejected",
        "rubric_json", "rubric_consistency_hit_rate", "rubric_tier_counts",
        "pair_sources", "synthetic_fallback_used", "source_run_id",
    }
    assert expected.issubset(cols)
