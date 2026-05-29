#!/usr/bin/env python3
from __future__ import annotations
"""
Proxy bank for Experiment 1 — the core authored artifact.

For each task we author 8-12 proxy checks across three classes:
  * valid       — genuinely tracks correctness (often executes & compares),
  * confounded  — correlates on typical outputs but DECOUPLES under mutation
                  (surface/structural checks: right clauses, right field names),
  * irrelevant  — near-zero causal link to correctness (length, casing, comments).

Author discipline (spec section 4):
  * authored BEFORE running the gate; no peeking at gate scores;
  * authored WITHOUT per-output gold verdicts (only task spec + reference idea);
  * `intended_class` is the author's hypothesis, used ONLY for stratified analysis,
    NEVER shown to the gate, NEVER used to compute empirical_validity.

INDEPENDENCE: this file shares NO helpers with gold/. The valid executable proxies
re-implement their own seeded DB / instance set so the proxy bank stands alone.

empirical_validity = Matthews correlation coefficient (MCC) between a proxy's
per-output verdicts and the gold verdicts across the population.

For `llm_judged` proxies, `impl` carries the judge prompt used in real mode; it also
carries a `mock_predicate` so the deterministic pipeline runs fully offline. In a real
(keyed) run the model judges each output from the prompt text alone.
"""

import json
import re
import sqlite3
from random import Random
from typing import Callable, Optional

from sklearn.metrics import matthews_corrcoef, balanced_accuracy_score

from .models import ProxyCheck, ProxyKind, IntendedClass, ProxyResult, Output


# ===========================================================================
# Independent SQL execution substrate (NO shared helpers with gold/)
# ===========================================================================

_PROXY_DDL = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, tier TEXT);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER,
                     amount_cents INTEGER, status TEXT);
"""


def _proxy_db() -> sqlite3.Connection:
    """An independently-seeded DB (different seed/size than the gold's)."""
    rng = Random(424242)
    conn = sqlite3.connect(":memory:")
    conn.executescript(_PROXY_DDL)
    custs, orders, oid = [], [], 1
    for cid in range(1, 21):
        custs.append((cid, f"C{cid}", ["free", "pro", "enterprise"][cid % 3]))
        base = cid * 700 + 53
        for _ in range(rng.randint(2, 3)):
            orders.append((oid, cid, rng.randint(1, base), "paid")); oid += 1
        if rng.random() < 0.5:
            orders.append((oid, cid, rng.randint(100, 900), "refunded")); oid += 1
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", custs)
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?)", orders)
    conn.commit()
    return conn


_PROXY_REF_QUERY = {
    "sql_ltv_top10": ("SELECT c.customer_id, c.name, SUM(o.amount_cents) AS v "
                      "FROM customers c JOIN orders o ON c.customer_id=o.customer_id "
                      "WHERE o.status='paid' GROUP BY c.customer_id, c.name "
                      "ORDER BY v DESC LIMIT 10", True),
    "sql_revenue_by_tier": ("SELECT c.tier, SUM(o.amount_cents) "
                            "FROM customers c JOIN orders o ON c.customer_id=o.customer_id "
                            "WHERE o.status='paid' GROUP BY c.tier", False),
}

_SQL_FENCE = re.compile(r"```(?:sql)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)


def _extract_sql(text: str) -> str:
    m = _SQL_FENCE.search(text)
    body = re.sub(r"--[^\n]*", "", m.group(1) if m else text)
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    for s in reversed(stmts):
        if re.search(r"\bselect\b", s, re.IGNORECASE):
            return s
    return body.strip()


def _sql_result_matches_reference(task_id: str, text: str) -> bool:
    ref_q, ordered = _PROXY_REF_QUERY[task_id]
    conn = _proxy_db()
    try:
        try:
            ref = conn.execute(ref_q).fetchall()
        except Exception:
            return False
        try:
            got = conn.execute(_extract_sql(text)).fetchall()
        except Exception:
            return False
    finally:
        conn.close()
    norm = lambda rows: [tuple(str(c) for c in r) for r in rows]
    a, b = norm(ref), norm(got)
    return a == b if ordered else sorted(a) == sorted(b)


# ===========================================================================
# Independent JSON-Schema validation substrate
# ===========================================================================

from jsonschema import Draft202012Validator

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.+?\})\s*```", re.DOTALL | re.IGNORECASE)

# Independently authored instance sets (overlap conceptually with gold, not shared).
_PROXY_INSTANCES = {
    "billing_schema": [
        ({"tenant_id": "x", "plan": "pro", "pricing_model": "seat", "seats": 2,
          "amount_cents": 10, "currency": "USD"}, True),
        ({"tenant_id": "y", "plan": "free", "pricing_model": "usage",
          "amount_cents": 0, "currency": "EUR"}, True),
        ({"plan": "pro", "pricing_model": "seat", "amount_cents": 10, "currency": "USD"}, False),
        ({"tenant_id": "z", "plan": "platinum", "pricing_model": "seat",
          "amount_cents": 10, "currency": "USD"}, False),
        ({"tenant_id": "w", "plan": "pro", "pricing_model": "seat",
          "amount_cents": -1, "currency": "USD"}, False),
        ({"tenant_id": "v", "plan": "pro", "pricing_model": "seat",
          "amount_cents": 10, "currency": "usd"}, False),
    ],
    "event_schema": [
        ({"event_id": "evt_a1", "type": "invoice.paid", "created_at": 5, "data": {}}, True),
        ({"event_id": "evt_b2", "type": "subscription.updated", "created_at": 0,
          "data": {"x": 1}}, True),
        ({"type": "invoice.paid", "created_at": 5, "data": {}}, False),
        ({"event_id": "nope", "type": "invoice.paid", "created_at": 5, "data": {}}, False),
        ({"event_id": "evt_c", "type": "chargeback", "created_at": 5, "data": {}}, False),
        ({"event_id": "evt_d", "type": "invoice.paid", "created_at": -3, "data": {}}, False),
    ],
}


def _extract_schema(text: str) -> Optional[dict]:
    m = _JSON_FENCE.search(text)
    cand = m.group(1) if m else text.strip()
    if not m:
        s, e = cand.find("{"), cand.rfind("}")
        if s == -1 or e <= s:
            return None
        cand = cand[s:e + 1]
    try:
        obj = json.loads(cand)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _schema_classifies_all(task_id: str, text: str) -> bool:
    schema = _extract_schema(text)
    if schema is None:
        return False
    try:
        Draft202012Validator.check_schema(schema)
        v = Draft202012Validator(schema)
    except Exception:
        return False
    return all(v.is_valid(inst) == ok for inst, ok in _PROXY_INSTANCES[task_id])


# ===========================================================================
# Surface predicates (for confounded / irrelevant proxies)
# ===========================================================================

def _has(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda text: bool(rx.search(text))


def _schema_lists_fields(task_id: str, fields: list[str]) -> Callable[[str], bool]:
    def pred(text: str) -> bool:
        s = _extract_schema(text)
        if not isinstance(s, dict):
            return False
        props = set((s.get("properties") or {}).keys())
        return all(f in props for f in fields)
    return pred


def _schema_declares_required(task_id: str, fields: list[str]) -> Callable[[str], bool]:
    def pred(text: str) -> bool:
        s = _extract_schema(text)
        if not isinstance(s, dict):
            return False
        return set(fields).issubset(set(s.get("required") or []))
    return pred


def _line_count_under(n: int) -> Callable[[str], bool]:
    return lambda text: len([ln for ln in text.splitlines() if ln.strip()]) < n


# ===========================================================================
# Proxy bank (authored per task)
# ===========================================================================

def _llm(prompt: str, mock_predicate: Callable[[str], bool]) -> dict:
    return {"prompt": prompt, "mock_predicate": mock_predicate}


def _sql_proxies(tid: str) -> list[ProxyCheck]:
    P = lambda **kw: ProxyCheck(task_id=tid, **kw)
    ranking = _PROXY_REF_QUERY[tid][1]
    metric = "top 10 customers by lifetime value" if ranking else "net revenue per tier"
    proxies = [
        # --- valid ---
        P(proxy_id=f"{tid}::v_exec_equal", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.VALID,
          definition=("Execute the query against the database and assert its result set "
                      f"equals the reference result set for the {metric} (paid orders only, "
                      "refunds excluded)."),
          impl=(lambda text, t=tid: _sql_result_matches_reference(t, text))),
        P(proxy_id=f"{tid}::v_llm_correct", kind=ProxyKind.LLM_JUDGED,
          intended_class=IntendedClass.VALID,
          definition=(f"Judge whether the query correctly computes the {metric}, summing only "
                      "paid orders (excluding refunds) and joining customers to orders on the "
                      "customer key."),
          impl=_llm(f"Does this SQL correctly compute the {metric} excluding refunds? "
                    "Answer YES or NO.\n\n{output}",
                    lambda text, t=tid: _sql_result_matches_reference(t, text))),
        # --- confounded (the crux): right surface, wrong substance survives ---
        P(proxy_id=f"{tid}::c_clauses", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Assert the query text contains the expected clauses: an aggregation "
                      "(SUM), a GROUP BY, and a WHERE filter on status = 'paid'."
                      + (" Also ORDER BY ... DESC and LIMIT 10." if ranking else "")),
          impl=(lambda text: bool(re.search(r"\bsum\s*\(", text, re.I))
                and bool(re.search(r"group\s+by", text, re.I))
                and bool(re.search(r"status\s*=\s*'paid'", text, re.I))
                and (not ranking or (bool(re.search(r"order\s+by.+desc", text, re.I | re.S))
                                     and bool(re.search(r"limit\s+10", text, re.I)))))),
        P(proxy_id=f"{tid}::c_mentions_tables", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Assert the query references both the customers and orders tables and "
                      "performs a JOIN between them."),
          impl=(lambda text: bool(re.search(r"\bcustomers\b", text, re.I))
                and bool(re.search(r"\borders\b", text, re.I))
                and bool(re.search(r"\bjoin\b", text, re.I)))),
        P(proxy_id=f"{tid}::c_llm_looks_right", kind=ProxyKind.LLM_JUDGED,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Judge whether the query 'looks like' a lifetime-value/revenue query: "
                      "does it mention the right tables, an aggregate, and a paid-status filter?"),
          impl=_llm("Does this SQL mention the right tables, an aggregate function, and a "
                    "paid-status filter (regardless of whether the logic is fully correct)? "
                    "Answer YES or NO.\n\n{output}",
                    lambda text: bool(re.search(r"\bsum\s*\(|\bavg\s*\(|\bcount\s*\(", text, re.I))
                    and bool(re.search(r"status", text, re.I))
                    and bool(re.search(r"\bjoin\b", text, re.I)))),
        # --- irrelevant ---
        P(proxy_id=f"{tid}::i_short", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.IRRELEVANT,
          definition="Assert the query is concise — fewer than 20 non-blank lines.",
          impl=_line_count_under(20)),
        P(proxy_id=f"{tid}::i_has_comment", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.IRRELEVANT,
          definition="Assert the query includes at least one SQL comment (`--`).",
          impl=_has(r"--")),
        P(proxy_id=f"{tid}::i_llm_readable", kind=ProxyKind.LLM_JUDGED,
          intended_class=IntendedClass.IRRELEVANT,
          definition="Judge whether the query is readable and well-formatted (style only).",
          impl=_llm("Is this SQL readable and well-formatted (style only, ignore correctness)? "
                    "Answer YES or NO.\n\n{output}",
                    lambda text: len(text) < 400)),
    ]
    return proxies


def _schema_proxies(tid: str) -> list[ProxyCheck]:
    P = lambda **kw: ProxyCheck(task_id=tid, **kw)
    if tid == "billing_schema":
        fields = ["tenant_id", "plan", "pricing_model", "amount_cents", "currency"]
    else:
        fields = ["event_id", "type", "created_at", "data"]
    proxies = [
        # --- valid ---
        P(proxy_id=f"{tid}::v_validate_instances", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.VALID,
          definition=("Validate the schema against a battery of well-formed records (which must "
                      "be accepted) and malformed records (which must be rejected); pass only if "
                      "every record is classified correctly."),
          impl=(lambda text, t=tid: _schema_classifies_all(t, text))),
        P(proxy_id=f"{tid}::v_llm_enforces", kind=ProxyKind.LLM_JUDGED,
          intended_class=IntendedClass.VALID,
          definition=("Judge whether the schema actually ENFORCES the stated constraints (required "
                      "fields, enums, types, numeric bounds, pattern, no unknown fields) such that "
                      "malformed records would be rejected."),
          impl=_llm("Would this JSON Schema reject records that omit required fields, use wrong "
                    "types/enums, violate numeric bounds or patterns, or add unknown fields? "
                    "Answer YES or NO.\n\n{output}",
                    lambda text, t=tid: _schema_classifies_all(t, text))),
        # --- confounded ---
        P(proxy_id=f"{tid}::c_lists_props", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Assert the schema declares all the expected property names under "
                      "`properties`."),
          impl=_schema_lists_fields(tid, fields)),
        P(proxy_id=f"{tid}::c_declares_required", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Assert the schema's `required` array lists the mandatory fields."),
          impl=_schema_declares_required(tid, fields)),
        P(proxy_id=f"{tid}::c_llm_mentions", kind=ProxyKind.LLM_JUDGED,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Judge whether the schema mentions all the expected fields and looks like a "
                      "plausible schema for the domain (presence of fields, not enforcement)."),
          impl=_llm("Does this JSON Schema mention all the expected fields and look plausible for "
                    "the domain? (Presence only, ignore whether constraints are enforced.) "
                    "Answer YES or NO.\n\n{output}",
                    _schema_lists_fields(tid, fields))),
        P(proxy_id=f"{tid}::c_has_type_object", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.CONFOUNDED,
          definition=("Assert the schema declares type 'object' and contains at least one enum or "
                      "pattern somewhere."),
          impl=(lambda text: '"type": "object"' in text.replace("'", '"')
                and ("enum" in text or "pattern" in text))),
        # --- irrelevant ---
        P(proxy_id=f"{tid}::i_has_schema_kw", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.IRRELEVANT,
          definition="Assert the document includes a `$schema` declaration.",
          impl=_has(r"\$schema")),
        P(proxy_id=f"{tid}::i_short", kind=ProxyKind.EXECUTABLE,
          intended_class=IntendedClass.IRRELEVANT,
          definition="Assert the schema document is concise — fewer than 40 non-blank lines.",
          impl=_line_count_under(40)),
        P(proxy_id=f"{tid}::i_llm_pretty", kind=ProxyKind.LLM_JUDGED,
          intended_class=IntendedClass.IRRELEVANT,
          definition="Judge whether the JSON is pretty-printed and indented (style only).",
          impl=_llm("Is this JSON pretty-printed and consistently indented (style only)? "
                    "Answer YES or NO.\n\n{output}",
                    lambda text: "\n  " in text)),
    ]
    return proxies


def build_proxy_bank(task) -> list[ProxyCheck]:
    return _sql_proxies(task.task_id) if task.family == "sql" else _schema_proxies(task.task_id)


# ===========================================================================
# Runner + empirical validity
# ===========================================================================

def _run_predicate(proxy: ProxyCheck, text: str, mock: bool, judge=None) -> bool:
    if proxy.kind == ProxyKind.EXECUTABLE:
        return bool(proxy.impl(text))
    # llm_judged
    if mock or judge is None:
        return bool(proxy.impl["mock_predicate"](text))
    return bool(judge(proxy.impl["prompt"], text))


def run_proxy(proxy: ProxyCheck, outputs: list[Output], mock: bool = True,
              judge=None) -> ProxyResult:
    """Run a proxy over the population and compute empirical_validity (MCC) vs gold."""
    verdicts: dict[str, bool] = {}
    gold: list[int] = []
    pred: list[int] = []
    for o in outputs:
        v = _run_predicate(proxy, o.text, mock, judge)
        verdicts[o.output_id] = v
        gold.append(1 if (o.gold_verdict or 0) >= 0.5 else 0)
        pred.append(1 if v else 0)

    # MCC is undefined if either vector is constant; sklearn returns 0.0 then.
    if len(set(gold)) < 2 or len(set(pred)) < 2:
        mcc = 0.0
    else:
        mcc = float(matthews_corrcoef(gold, pred))
    try:
        bacc = float(balanced_accuracy_score(gold, pred))
    except Exception:
        bacc = 0.0

    return ProxyResult(proxy_id=proxy.proxy_id, task_id=proxy.task_id,
                       per_output_verdicts=verdicts, empirical_validity=mcc,
                       balanced_accuracy=bacc, n_outputs=len(outputs))
