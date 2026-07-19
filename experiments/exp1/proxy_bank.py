"""The proxy bank (SPEC.md section 4) — the core authored artifact.

Authoring discipline, enforced and tested:

- Authored against the task spec and reference output only, BEFORE any gate
  run, and without looking at per-output gold verdicts. Frozen thereafter.
- NO shared helpers with gold/: this module re-implements its own extractors,
  its own SQL substrate (different seed and data generator), its own schema
  instance battery (smaller), and its own CSV fixtures. Valid executable
  proxies therefore reach correctness conclusions independently of the gold.
  A test asserts this module never imports from experiments.exp1.gold.
- intended_class is the author's hypothesis, used only for stratified
  analysis; empirical_validity is MCC of proxy verdicts vs gold verdicts.

Each task carries 10-11 proxies spanning valid / confounded / irrelevant and
mixing executable with llm_judged. llm_judged proxies hold a judge prompt for
keyed runs and a deterministic mock_predicate for offline pipeline runs.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .models import IntendedClass, Output, ProxyCheck, ProxyKind, ProxyResult

# ---------------------------------------------------------------------------
# Metrics (spec section 4): MCC + balanced accuracy of proxy vs gold verdicts.
# ---------------------------------------------------------------------------


def mcc(proxy: list[bool], gold_v: list[bool]) -> float:
    tp = sum(1 for p, g in zip(proxy, gold_v) if p and g)
    tn = sum(1 for p, g in zip(proxy, gold_v) if not p and not g)
    fp = sum(1 for p, g in zip(proxy, gold_v) if p and not g)
    fn = sum(1 for p, g in zip(proxy, gold_v) if not p and g)
    denom = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
    if denom == 0:
        return 0.0  # degenerate (constant proxy or constant gold)
    return (tp * tn - fp * fn) / denom


def balanced_accuracy(proxy: list[bool], gold_v: list[bool]) -> float:
    pos = [(p, g) for p, g in zip(proxy, gold_v) if g]
    neg = [(p, g) for p, g in zip(proxy, gold_v) if not g]
    tpr = sum(1 for p, _ in pos if p) / len(pos) if pos else 0.5
    tnr = sum(1 for p, _ in neg if not p) / len(neg) if neg else 0.5
    return (tpr + tnr) / 2


# ---------------------------------------------------------------------------
# Local extractors (deliberately re-implemented; no imports from gold/).
# ---------------------------------------------------------------------------

_SQL_FENCE_RE = re.compile(r"```(?:sqlite|sql)?[^\S\n]*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_PY_FENCE_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

_LEADING_SQL_COMMENTS = re.compile(r"^\s*(?:--[^\n]*\n\s*)*")


def _sql_of(text: str) -> str:
    """Last fenced block that reads as a query (skips DDL echoes/examples)."""
    picked = ""
    for block in _SQL_FENCE_RE.findall(text):
        head = _LEADING_SQL_COMMENTS.sub("", block.strip())
        if re.match(r"(?i)^(select|with)\b", head):
            picked = block.strip()
    if picked:
        return picked
    if "```" not in text:
        head = _LEADING_SQL_COMMENTS.sub("", text.strip())
        if re.match(r"(?i)^(select|with)\b", head):
            return text.strip()
    return ""


def _schema_of(text: str) -> Optional[dict]:
    """Last fenced JSON object that looks like a schema (an appended example
    instance must not shadow it)."""
    dicts = []
    for block in _JSON_FENCE_RE.findall(text):
        try:
            parsed = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            dicts.append(parsed)
    schema_like = [d for d in dicts
                   if "properties" in d or "$schema" in d or "$defs" in d]
    if schema_like:
        return schema_like[-1]
    return dicts[-1] if dicts else None


def _python_of(text: str) -> str:
    """Last block defining parse_csv (a trailing usage example must not
    shadow the implementation)."""
    blocks = [b.strip() for b in _PY_FENCE_RE.findall(text)]
    defining = [b for b in blocks if "def parse_csv" in b]
    if defining:
        return defining[-1]
    return blocks[-1] if blocks else ""


# ---------------------------------------------------------------------------
# Independent SQL substrate: same pinned schema (it is part of the task), but
# its own data generator, seed, and independently authored reference queries.
# ---------------------------------------------------------------------------

_PROXY_SEED = 424242


def _proxy_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            signup_tier TEXT NOT NULL
        );
        CREATE TABLE payments (
            payment_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL,
            type TEXT NOT NULL,
            paid_at TEXT NOT NULL
        );
        """
    )
    rng = random.Random(_PROXY_SEED)
    tiers = ["enterprise", "free", "pro"]
    pid = 1
    for cid in range(1, 31):
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?)",
            (cid, f"Acct {cid}", f"acct{cid}@test.io", tiers[rng.randrange(3)]),
        )
        if cid % 9 == 0:  # a few customers with no payments
            continue
        for _ in range(rng.randint(1, 9)):
            conn.execute(
                "INSERT INTO payments VALUES (?, ?, ?, ?, ?)",
                (pid, cid, rng.randint(500, 90_000), "charge",
                 f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"),
            )
            pid += 1
        if rng.random() < 0.5:
            conn.execute(
                "INSERT INTO payments VALUES (?, ?, ?, ?, ?)",
                (pid, cid, rng.randint(100, 20_000), "refund",
                 f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"),
            )
            pid += 1
    conn.commit()
    return conn


# Independently authored reference semantics (not copied from gold/sql_gold).
_PROXY_REF_SQL = {
    "sql_ltv_top10": """
        SELECT cu.customer_id, cu.name,
               COALESCE(SUM(CASE pa.type WHEN 'charge' THEN pa.amount_cents
                                         WHEN 'refund' THEN -pa.amount_cents END), 0)
                   AS ltv
        FROM customers cu LEFT JOIN payments pa USING (customer_id)
        GROUP BY cu.customer_id ORDER BY ltv DESC LIMIT 10
    """,
    "sql_revenue_by_tier": """
        SELECT cu.signup_tier,
               COALESCE(SUM(CASE pa.type WHEN 'charge' THEN pa.amount_cents
                                         WHEN 'refund' THEN -pa.amount_cents END), 0)
                   AS net
        FROM customers cu LEFT JOIN payments pa USING (customer_id)
        GROUP BY cu.signup_tier ORDER BY net DESC
    """,
}


def _proxy_exec(sql: str) -> Optional[list[tuple]]:
    if not sql:
        return None
    conn = _proxy_db()
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _sql_matches_independent_ref(task_id: str):
    def check(text: str) -> bool:
        rows = _proxy_exec(_sql_of(text))
        return rows is not None and rows == _proxy_exec(_PROXY_REF_SQL[task_id])

    return check


def _sql_top_row_matches(task_id: str):
    def check(text: str) -> bool:
        rows = _proxy_exec(_sql_of(text))
        ref = _proxy_exec(_PROXY_REF_SQL[task_id])
        return bool(rows) and bool(ref) and rows[0] == ref[0]

    return check


def _sql_row_count_is(n: int):
    def check(text: str) -> bool:
        rows = _proxy_exec(_sql_of(text))
        return rows is not None and len(rows) == n

    return check


def _sql_executes(text: str) -> bool:
    return _proxy_exec(_sql_of(text)) is not None


# ---------------------------------------------------------------------------
# Independent schema instance battery (smaller than the gold's — a realistic
# "weaker but valid" check) — authored from the task contract only.
# ---------------------------------------------------------------------------

_PROXY_PLAN = {"pricing_model": "seat", "price_per_seat_cents": 2500,
               "included_usage_units": 50}

_PROXY_VALID_INSTANCES = [
    {"subscription_id": "s1", "tenant_id": "t1", "status": "active", "seats": 3,
     "plan": dict(_PROXY_PLAN)},
    {"subscription_id": "s2", "tenant_id": "t2", "status": "trial", "seats": 1,
     "plan": {"pricing_model": "usage", "price_per_seat_cents": 0,
              "included_usage_units": 10_000},
     "usage_records": [{"unit": "gb", "quantity": 12.5}]},
]

_PROXY_INVALID_INSTANCES = [
    {"subscription_id": "s3", "status": "active", "seats": 3,
     "plan": dict(_PROXY_PLAN)},  # tenant_id missing
    {"subscription_id": "s4", "tenant_id": "t4", "status": "archived", "seats": 3,
     "plan": dict(_PROXY_PLAN)},  # bad status
    {"subscription_id": "s5", "tenant_id": "t5", "status": "active", "seats": 0,
     "plan": dict(_PROXY_PLAN)},  # zero seats
    {"subscription_id": "s6", "tenant_id": "t6", "status": "active", "seats": 2,
     "plan": dict(_PROXY_PLAN), "coupon": "SAVE10"},  # extra field
]


def _schema_battery_check(text: str) -> bool:
    import jsonschema
    from jsonschema import Draft202012Validator

    schema = _schema_of(text)
    if schema is None:
        return False
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except jsonschema.exceptions.SchemaError:
        return False
    return all(validator.is_valid(i) for i in _PROXY_VALID_INSTANCES) and all(
        not validator.is_valid(i) for i in _PROXY_INVALID_INSTANCES
    )


def _schema_parses(text: str) -> bool:
    import jsonschema
    from jsonschema import Draft202012Validator

    schema = _schema_of(text)
    if schema is None:
        return False
    try:
        Draft202012Validator.check_schema(schema)
        return True
    except jsonschema.exceptions.SchemaError:
        return False


def _schema_prop(path: list[str], predicate):
    def check(text: str) -> bool:
        node = _schema_of(text)
        if node is None:
            return False
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return False
            node = node[key]
        try:
            return bool(predicate(node))
        except (TypeError, KeyError):
            return False

    return check


def _schema_depth(text: str) -> bool:
    schema = _schema_of(text)

    def depth(node) -> int:
        if isinstance(node, dict):
            return 1 + max((depth(v) for v in node.values()), default=0)
        if isinstance(node, list):
            return 1 + max((depth(v) for v in node), default=0)
        return 0

    return schema is not None and depth(schema) >= 4


# ---------------------------------------------------------------------------
# Independent CSV fixtures (smaller set, authored from the contract only).
# ---------------------------------------------------------------------------

_PROXY_CSV_FIXTURES: list[tuple[str, list[list[str]]]] = [
    ("p,q\n7,8\n", [["p", "q"], ["7", "8"]]),
    ("m;n;o\n4;5;6\n", [["m", "n", "o"], ["4", "5", "6"]]),
    ('id,quote\n1,"a,b"\n', [["id", "quote"], ["1", "a,b"]]),
    (" u , v \nx,y\n", [["u", "v"], ["x", "y"]]),
    ("k,l\n\nz,w\n", [["k", "l"], ["z", "w"]]),
]

# Imports the candidate (so its __main__ demo blocks never run) and moves
# data through files (so candidate prints cannot corrupt the channel).
_PROXY_CSV_DRIVER = """
import json
import sys
sys.path.insert(0, ".")
import cand
out = []
for text in json.load(open("cases.json", encoding="utf-8")):
    try:
        out.append(cand.parse_csv(text))
    except Exception:
        out.append(None)
json.dump(out, open("out.json", "w", encoding="utf-8"))
"""


def _run_csv_candidate(code: str, cases: list[str]) -> Optional[list]:
    if not code or "def parse_csv" not in code:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "cand.py").write_text(code, encoding="utf-8")
        (Path(tmp) / "runner.py").write_text(_PROXY_CSV_DRIVER, encoding="utf-8")
        (Path(tmp) / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "runner.py"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return None
        out_path = Path(tmp) / "out.json"
        if proc.returncode != 0 or not out_path.exists():
            return None
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def _csv_own_fixtures(text: str) -> bool:
    results = _run_csv_candidate(
        _python_of(text), [t for t, _ in _PROXY_CSV_FIXTURES]
    )
    if results is None:
        return False
    return all(r == e for r, (_, e) in zip(results, _PROXY_CSV_FIXTURES))


def _csv_simple_case(text: str) -> bool:
    results = _run_csv_candidate(_python_of(text), ["a,b\n1,2\n"])
    return results is not None and results[0] == [["a", "b"], ["1", "2"]]


def _csv_runs_on_quotes(text: str) -> bool:
    results = _run_csv_candidate(_python_of(text), ['"x","y"\n'])
    return results is not None and results[0] is not None


def _csv_defines_and_runs(text: str) -> bool:
    results = _run_csv_candidate(_python_of(text), ["a\n"])
    return results is not None and results[0] is not None


# ---------------------------------------------------------------------------
# Text-surface predicates (the confounded / irrelevant workhorses).
# ---------------------------------------------------------------------------


def _sql_text_re(pattern: str):
    regex = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    return lambda text: bool(regex.search(_sql_of(text)))


def _sql_under_lines(n: int):
    return lambda text: 0 < len(_sql_of(text).splitlines()) < n


def _code_text(predicate):
    return lambda text: predicate(_python_of(text))


# ---------------------------------------------------------------------------
# The bank.
# ---------------------------------------------------------------------------


def _proxy(task_id, pid, definition, kind, intended, impl=None, judge=None, mock=None):
    return ProxyCheck(
        proxy_id=f"{task_id}::{pid}",
        task_id=task_id,
        definition=definition,
        kind=kind,
        intended_class=intended,
        impl=impl,
        judge_prompt=judge,
        mock_predicate=mock,
    )


def build_proxy_bank() -> dict[str, list[ProxyCheck]]:
    E, L = ProxyKind.EXECUTABLE, ProxyKind.LLM_JUDGED
    V, C, I = IntendedClass.VALID, IntendedClass.CONFOUNDED, IntendedClass.IRRELEVANT
    bank: dict[str, list[ProxyCheck]] = {}

    # ----- sql_ltv_top10 ---------------------------------------------------
    t = "sql_ltv_top10"
    bank[t] = [
        _proxy(t, "exec_matches_ref", "Execute the query against an independently seeded database with the same schema and assert its result table exactly equals the result of a known-correct top-10-LTV reference query (same columns, order, and values).", E, V, impl=_sql_matches_independent_ref(t)),
        _proxy(t, "exec_top_row_matches", "Execute the query against an independently seeded database and assert its first returned row equals the first row of a known-correct reference query (the true top customer by lifetime value).", E, V, impl=_sql_top_row_matches(t)),
        _proxy(t, "exec_returns_10_rows", "Execute the query against a database with the task schema and assert it runs without error and returns exactly 10 rows.", E, C, impl=_sql_row_count_is(10)),
        _proxy(t, "text_order_desc_limit10", "Assert the query text contains an ORDER BY ... DESC clause and a LIMIT 10 clause.", E, C, impl=_sql_text_re(r"ORDER\s+BY[\s\S]*?DESC[\s\S]*?LIMIT\s+10")),
        _proxy(t, "text_mentions_refund", "Assert the query text mentions refunds (contains the string 'refund'), indicating refunds were considered.", E, C, impl=_sql_text_re(r"refund")),
        _proxy(t, "text_has_group_by", "Assert the query text contains a GROUP BY clause, indicating per-customer aggregation.", E, C, impl=_sql_text_re(r"GROUP\s+BY")),
        _proxy(t, "exec_no_error", "Execute the query against a database with the task schema and assert it executes without raising a SQL error.", E, C, impl=_sql_executes),
        _proxy(t, "text_under_20_lines", "Assert the query is under 20 lines long.", E, I, impl=_sql_under_lines(20)),
        _proxy(t, "text_uses_cte", "Assert the query uses a common table expression (a WITH clause).", E, I, impl=_sql_text_re(r"^\s*WITH\b")),
        _proxy(t, "llm_ltv_semantics", "Ask an LLM judge: does this query correctly compute each customer's lifetime value as total charges minus total refunds in cents, include customers with no payments as zero, and return exactly customer_id, name, lifetime_value_cents for the top 10 ordered descending?", L, V,
               judge="You are verifying a SQLite query for this task: return the top 10 customers by lifetime value, where lifetime value = total 'charge' cents minus total 'refund' cents from a payments table (customer_id, amount_cents, type), joined to customers (customer_id, name). Columns must be customer_id, name, lifetime_value_cents, ordered by lifetime_value_cents DESC, LIMIT 10, with customers lacking payments counting as 0. Answer strictly PASS or FAIL: does the following output's query satisfy ALL of that?\n\n{output}",
               mock=lambda text: bool(re.search(r"refund", _sql_of(text), re.I)) and bool(re.search(r"(ELSE\s+0|COALESCE)", _sql_of(text), re.I)) and bool(re.search(r"ORDER\s+BY\s+\S*ltv|ORDER\s+BY\s+lifetime_value_cents\s+DESC", _sql_of(text), re.I)) and bool(re.search(r"LIMIT\s+10", _sql_of(text), re.I)) and not re.search(r"AVG\s*\(", _sql_of(text), re.I)),
        _proxy(t, "llm_readability", "Ask an LLM judge: is this SQL well-formatted and readable, with clear aliases and sensible layout?", L, I,
               judge="Answer strictly PASS or FAIL: is the SQL in the following output well-formatted and readable, with clear aliases and a sensible multi-line layout?\n\n{output}",
               mock=lambda text: len(_sql_of(text).splitlines()) >= 5 and bool(re.search(r"\n(FROM|from)\b", _sql_of(text)))),
    ]

    # ----- sql_revenue_by_tier --------------------------------------------
    t = "sql_revenue_by_tier"
    bank[t] = [
        _proxy(t, "exec_matches_ref", "Execute the query against an independently seeded database with the same schema and assert its result table exactly equals the result of a known-correct net-revenue-per-tier reference query (same columns, order, and values).", E, V, impl=_sql_matches_independent_ref(t)),
        _proxy(t, "exec_returns_3_rows", "Execute the query against a database with the task schema and assert it runs without error and returns exactly one row per tier (3 rows).", E, C, impl=_sql_row_count_is(3)),
        _proxy(t, "text_order_desc", "Assert the query text contains an ORDER BY ... DESC clause.", E, C, impl=_sql_text_re(r"ORDER\s+BY[\s\S]*?DESC")),
        _proxy(t, "text_mentions_refund", "Assert the query text mentions refunds (contains the string 'refund').", E, C, impl=_sql_text_re(r"refund")),
        _proxy(t, "text_group_by_tier", "Assert the query text groups by the signup_tier column (GROUP BY ... signup_tier).", E, C, impl=_sql_text_re(r"GROUP\s+BY[\s\S]*?signup_tier")),
        _proxy(t, "exec_no_error", "Execute the query against a database with the task schema and assert it executes without raising a SQL error.", E, C, impl=_sql_executes),
        _proxy(t, "text_under_15_lines", "Assert the query is under 15 lines long.", E, I, impl=_sql_under_lines(15)),
        _proxy(t, "text_uppercase_keywords", "Assert the query writes its SQL keywords in uppercase (SELECT rather than select).", E, I, impl=_sql_text_re(r"\bSELECT\b")),
        _proxy(t, "llm_net_revenue_semantics", "Ask an LLM judge: does this query correctly compute net revenue per signup tier as total charges minus total refunds in cents, returning exactly signup_tier and net_revenue_cents, one row per tier, ordered by net revenue descending?", L, V,
               judge="You are verifying a SQLite query for this task: return net revenue per signup tier, where net revenue = total 'charge' cents minus total 'refund' cents from payments (customer_id, amount_cents, type) joined to customers (customer_id, signup_tier). Columns must be signup_tier, net_revenue_cents, one row per tier, ordered by net_revenue_cents DESC. Answer strictly PASS or FAIL: does the following output's query satisfy ALL of that?\n\n{output}",
               # Contract-derived heuristic only (no population-specific
               # tokens): joining customers ON signup_tier fans out rows and
               # double-counts — a semantic flaw, whatever the alias.
               mock=lambda text: bool(re.search(r"refund", _sql_of(text), re.I)) and bool(re.search(r"signup_tier", _sql_of(text), re.I)) and bool(re.search(r"(DESC|desc)", _sql_of(text))) and not re.search(r"join\s+customers\s+\w+\s+on\s+\w+\.signup_tier\s*=", _sql_of(text), re.I) and bool(re.search(r"-\s*(COALESCE|coalesce|SUM|sum)|WHEN\s+'refund'\s+THEN\s+-|when\s+'refund'\s+then\s+-", _sql_of(text)))),
        _proxy(t, "llm_readability", "Ask an LLM judge: is this SQL well-formatted and readable?", L, I,
               judge="Answer strictly PASS or FAIL: is the SQL in the following output well-formatted and readable, with clear aliases and a sensible multi-line layout?\n\n{output}",
               mock=lambda text: len(_sql_of(text).splitlines()) >= 5 and bool(re.search(r"\n(FROM|from)\b", _sql_of(text)))),
    ]

    # ----- billing_schema --------------------------------------------------
    t = "billing_schema"
    bank[t] = [
        _proxy(t, "battery_accepts_rejects", "Validate an independently authored battery of labeled subscription instances against the schema and assert it accepts every valid instance and rejects every invalid one.", E, V, impl=_schema_battery_check),
        _proxy(t, "parses_as_schema", "Assert the output contains a JSON object that is itself a structurally valid JSON Schema (draft 2020-12).", E, C, impl=_schema_parses),
        _proxy(t, "required_has_tenant", "Assert the schema's top-level required array includes tenant_id.", E, C, impl=_schema_prop(["required"], lambda r: "tenant_id" in r)),
        _proxy(t, "additional_props_false", "Assert the schema sets additionalProperties to false at the top level.", E, C, impl=_schema_prop(["additionalProperties"], lambda v: v is False)),
        _proxy(t, "status_enum_exact", "Assert the schema's status property is an enum of exactly trial, active, past_due, canceled.", E, C, impl=_schema_prop(["properties", "status", "enum"], lambda e: sorted(e) == sorted(["trial", "active", "past_due", "canceled"]))),
        _proxy(t, "seats_integer_min1", "Assert the schema types seats as an integer with minimum 1.", E, C, impl=_schema_prop(["properties", "seats"], lambda s: s.get("type") == "integer" and s.get("minimum") == 1)),
        _proxy(t, "nesting_depth", "Assert the schema JSON nests at least four levels deep, indicating a structured design.", E, I, impl=_schema_depth),
        _proxy(t, "has_annotations", "Assert the schema carries a title or description annotation.", E, I, impl=lambda text: (lambda s: s is not None and ("title" in s or "description" in s))(_schema_of(text))),
        _proxy(t, "llm_contract_check", "Ask an LLM judge: does this JSON Schema enforce the full pinned contract — required fields, status and pricing_model enums, integer seats >= 1, integer plan amounts >= 0, usage_records item shape, and no extra top-level fields?", L, V,
               judge="You are verifying a JSON Schema (draft 2020-12) for a SaaS subscription record. The contract: required top-level fields subscription_id, tenant_id (non-empty strings), status (enum trial/active/past_due/canceled), seats (integer >= 1), plan (object requiring pricing_model enum seat/usage/hybrid, price_per_seat_cents integer >= 0, included_usage_units integer >= 0); optional usage_records array of {unit: non-empty string, quantity: number >= 0}; NO other top-level fields allowed. Answer strictly PASS or FAIL: does the schema in the following output enforce ALL of that?\n\n{output}",
               mock=lambda text: (lambda s: s is not None and set(s.get("required", [])) == {"subscription_id", "tenant_id", "status", "seats", "plan"} and s.get("additionalProperties") is False and s.get("properties", {}).get("seats", {}).get("minimum") == 1 and s.get("properties", {}).get("seats", {}).get("type") == "integer")(_schema_of(text))),
        _proxy(t, "llm_professional", "Ask an LLM judge: does this schema look professionally authored (annotations, consistent style, sensible naming)?", L, I,
               judge="Answer strictly PASS or FAIL: does the JSON Schema in the following output look professionally authored — annotations such as title/description, consistent style, sensible naming?\n\n{output}",
               mock=lambda text: (lambda s: s is not None and "$schema" in s and ("title" in s or "description" in s))(_schema_of(text))),
    ]

    # ----- csv_parser ------------------------------------------------------
    t = "csv_parser"
    bank[t] = [
        _proxy(t, "own_fixtures_pass", "Run the parse_csv function on an independently authored set of messy-CSV fixtures (delimiters, quoting, stripping, blank lines) and assert every parse matches the contract's expected output.", E, V, impl=_csv_own_fixtures),
        _proxy(t, "simple_case_correct", "Run parse_csv on a simple two-row comma CSV and assert the parse is exactly correct.", E, C, impl=_csv_simple_case),
        _proxy(t, "runs_on_quoted_input", "Run parse_csv on a quoted-field input and assert it returns without raising an exception.", E, C, impl=_csv_runs_on_quotes),
        _proxy(t, "defines_and_runs", "Assert the output defines a parse_csv function that imports and runs without error.", E, C, impl=_csv_defines_and_runs),
        _proxy(t, "text_handles_quotes", "Assert the code contains double-quote handling logic (references the '\"' character).", E, C, impl=_code_text(lambda c: "'\"'" in c or '"\\""' in c or 'char == quote' in c)),
        _proxy(t, "text_strips_fields", "Assert the code calls .strip( somewhere, indicating whitespace trimming.", E, C, impl=_code_text(lambda c: ".strip(" in c)),
        _proxy(t, "under_60_lines", "Assert the code is under 60 lines.", E, I, impl=_code_text(lambda c: 0 < len(c.splitlines()) < 60)),
        _proxy(t, "has_type_hints", "Assert the function signature carries type hints (-> list).", E, I, impl=_code_text(lambda c: "-> list" in c)),
        _proxy(t, "llm_contract_correct", "Ask an LLM judge: does this parse_csv implementation satisfy the full pinned contract — delimiter detection with comma/semicolon/tab tie-break, quoted fields with doubled-quote escapes and literal newlines, stripping of unquoted fields only, and skipping of whitespace-only rows?", L, V,
               judge="You are verifying a Python function against this contract: parse_csv(text) -> list[list[str]]; delimiter = most frequent of , ; tab in first non-empty line with ties broken in that order; double-quoted fields keep delimiters/newlines literally and decode doubled quotes; unquoted fields are stripped of spaces/tabs, quoted content preserved verbatim; whitespace-only lines are skipped; ragged rows returned as-is. Answer strictly PASS or FAIL: does the code in the following output implement ALL of that?\n\n{output}",
               mock=lambda text: (lambda c: '""' in c.replace("'", '"') and ".strip(" in c and ("continue" in c or "while" in c) and not ("splitlines()" in c and "split(delimiter)" in c))(_python_of(text))),
        _proxy(t, "llm_code_quality", "Ask an LLM judge: is this Python code clean and well-documented (docstring or comments, clear names)?", L, I,
               judge="Answer strictly PASS or FAIL: is the Python code in the following output clean and well-documented, with a docstring or comments and clear names?\n\n{output}",
               mock=lambda text: (lambda c: '"""' in c or c.count("#") >= 2)(_python_of(text))),
    ]

    return bank


# ---------------------------------------------------------------------------
# Runner.
# ---------------------------------------------------------------------------


def run_proxy(proxy: ProxyCheck, outputs: list[Output], judge=None) -> ProxyResult:
    """judge: callable(judge_prompt, output_text) -> bool for keyed llm_judged
    runs; None -> use the deterministic mock predicate (offline mode)."""
    verdicts: dict[str, bool] = {}
    for output in outputs:
        if proxy.kind == ProxyKind.EXECUTABLE:
            verdict = bool(proxy.impl(output.text))
        elif judge is not None:
            verdict = bool(judge(proxy.judge_prompt, output.text))
        else:
            verdict = bool(proxy.mock_predicate(output.text))
        verdicts[output.output_id] = verdict
    proxy_v = [verdicts[o.output_id] for o in outputs]
    gold_v = [bool(o.gold_verdict) for o in outputs]
    return ProxyResult(
        proxy_id=proxy.proxy_id,
        per_output_verdicts=verdicts,
        empirical_validity=mcc(proxy_v, gold_v),
        balanced_accuracy=balanced_accuracy(proxy_v, gold_v),
        n_outputs=len(outputs),
    )


if __name__ == "__main__":
    from . import gold as _gold_pkg  # CLI preview only; bank itself stays independent
    from .population import build_population

    bank = build_proxy_bank()
    for task in _gold_pkg.build_tasks().values():
        pop = build_population(task)
        print(f"\n{task.task_id} (pass rate "
              f"{sum(1 for o in pop if o.gold_verdict)}/{len(pop)})")
        for proxy in bank[task.task_id]:
            result = run_proxy(proxy, pop)
            print(f"  MCC {result.empirical_validity:+.2f}  balacc {result.balanced_accuracy:.2f}  "
                  f"{proxy.intended_class.value:10s} {proxy.kind.value:10s} {proxy.proxy_id}")
