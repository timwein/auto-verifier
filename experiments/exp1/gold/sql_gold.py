#!/usr/bin/env python3
from __future__ import annotations
"""
SQL gold verifier for Experiment 1 — SELF-CONTAINED, EXECUTE-AND-COMPARE.

The repo has no executable SQL gold (deterministic_verifier.py only regex-checks
for `SELECT *`). So we build our own trustworthy ground truth here:

  * a deterministically-seeded in-memory SQLite database, and
  * a pinned *reference query* per task whose executed result set IS the truth.

`gold_verdict(task_id, candidate_text)` extracts the SQL from a candidate output,
executes it against the seeded DB, and returns 1.0 iff the result table equals the
reference query's result table (ordered for ranking tasks, set-compared otherwise).

IMPORTANT: This file is authored independently of proxy_bank.py and shares NO
helpers with it (spec author-discipline + user instruction).
"""

import re
import sqlite3
from dataclasses import dataclass
from random import Random
from typing import Optional


# ---------------------------------------------------------------------------
# Seeded dataset (deterministic — fixed RNG seed, distinct LTV values by design)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    tier        TEXT NOT NULL            -- 'free' | 'pro' | 'enterprise'
);
CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    status       TEXT NOT NULL,          -- 'paid' | 'refunded'
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
"""

_TIERS = ["free", "pro", "enterprise"]
_N_CUSTOMERS = 30
_SEED = 1729


def _seed_rows():
    """Deterministically generate customers + orders.

    Designed so that paid-only lifetime values are DISTINCT across customers,
    which makes the top-10 ranking (and thus the gold) unambiguous.
    """
    rng = Random(_SEED)
    customers = []
    for cid in range(1, _N_CUSTOMERS + 1):
        customers.append((cid, f"Customer_{cid:02d}", _TIERS[cid % 3]))

    orders = []
    oid = 1
    # Give each customer a distinct base paid total by spacing them out, then add
    # some refunded orders (which must NOT count toward LTV).
    for cid in range(1, _N_CUSTOMERS + 1):
        base = cid * 1000 + 137  # distinct, non-overlapping across customers
        # 2-4 paid orders summing to exactly `base`.
        n_paid = rng.randint(2, 4)
        cuts = sorted(rng.sample(range(1, base), n_paid - 1)) if n_paid > 1 else []
        prev = 0
        parts = []
        for c in cuts:
            parts.append(c - prev)
            prev = c
        parts.append(base - prev)
        for amt in parts:
            orders.append((oid, cid, amt, "paid"))
            oid += 1
        # 0-2 refunded orders (noise that confounders may wrongly include).
        for _ in range(rng.randint(0, 2)):
            orders.append((oid, cid, rng.randint(500, 5000), "refunded"))
            oid += 1

    rng.shuffle(orders)
    return customers, orders


def build_db() -> sqlite3.Connection:
    """Fresh in-memory seeded DB."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_DDL)
    customers, orders = _seed_rows()
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", customers)
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?)", orders)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Per-task reference queries (the gold definition)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SqlTaskSpec:
    task_id: str
    prompt: str
    reference_query: str
    ordered: bool          # True => row order is part of correctness (rankings)


SQL_TASKS = {
    "sql_ltv_top10": SqlTaskSpec(
        task_id="sql_ltv_top10",
        prompt=(
            "Given this SQLite schema:\n"
            "  customers(customer_id, name, tier)\n"
            "  orders(order_id, customer_id, amount_cents, status)  -- status is 'paid' or 'refunded'\n"
            "Write a SQL query returning the top 10 customers by lifetime value "
            "(sum of order amounts, EXCLUDING refunds), highest first. Return "
            "customer_id, name, and the lifetime value."
        ),
        reference_query=(
            "SELECT c.customer_id, c.name, SUM(o.amount_cents) AS ltv "
            "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
            "WHERE o.status = 'paid' "
            "GROUP BY c.customer_id, c.name "
            "ORDER BY ltv DESC LIMIT 10"
        ),
        ordered=True,
    ),
    "sql_revenue_by_tier": SqlTaskSpec(
        task_id="sql_revenue_by_tier",
        prompt=(
            "Given this SQLite schema:\n"
            "  customers(customer_id, name, tier)\n"
            "  orders(order_id, customer_id, amount_cents, status)  -- status is 'paid' or 'refunded'\n"
            "Write a SQL query returning the net revenue per customer tier "
            "(sum of paid order amounts, EXCLUDING refunds), grouped by tier."
        ),
        reference_query=(
            "SELECT c.tier, SUM(o.amount_cents) AS net_revenue "
            "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
            "WHERE o.status = 'paid' "
            "GROUP BY c.tier"
        ),
        ordered=False,
    ),
}


# ---------------------------------------------------------------------------
# Execution + comparison
# ---------------------------------------------------------------------------

_SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    """Pull the SQL statement from a candidate output (fenced block if present)."""
    m = _SQL_BLOCK.search(text)
    body = m.group(1) if m else text
    # Take the last SELECT-bearing statement; strip trailing semicolons/comments.
    body = re.sub(r"--[^\n]*", "", body)
    statements = [s.strip() for s in body.split(";") if s.strip()]
    for stmt in reversed(statements):
        if re.search(r"\bselect\b", stmt, re.IGNORECASE):
            return stmt
    return body.strip()


def _normalize_rows(rows, ordered: bool):
    """Normalize a result table to a comparable form (cell values as strings)."""
    norm = [tuple("" if c is None else str(c) for c in row) for row in rows]
    return norm if ordered else sorted(norm)


def run_sql(conn: sqlite3.Connection, sql: str):
    """Execute SQL, returning (rows, error_message)."""
    try:
        cur = conn.execute(sql)
        return cur.fetchall(), None
    except Exception as e:  # sqlite3 errors, etc.
        return None, f"{type(e).__name__}: {e}"


def reference_result(task_id: str):
    spec = SQL_TASKS[task_id]
    conn = build_db()
    try:
        rows, err = run_sql(conn, spec.reference_query)
        if err:
            raise RuntimeError(f"Reference query failed for {task_id}: {err}")
        return rows
    finally:
        conn.close()


def gold_verdict(task_id: str, candidate_text: str) -> float:
    """1.0 iff the candidate's executed result table equals the reference's."""
    spec = SQL_TASKS[task_id]
    ref_rows = reference_result(task_id)
    sql = extract_sql(candidate_text)
    conn = build_db()
    try:
        cand_rows, err = run_sql(conn, sql)
    finally:
        conn.close()
    if err is not None or cand_rows is None:
        return 0.0
    return 1.0 if _normalize_rows(cand_rows, spec.ordered) == _normalize_rows(ref_rows, spec.ordered) else 0.0


def reference_output(task_id: str) -> str:
    """The known-correct candidate text (reference anchor) for a task."""
    spec = SQL_TASKS[task_id]
    return f"```sql\n{spec.reference_query};\n```"
