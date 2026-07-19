"""Executable gold for the two SQL tasks (DESIGN_NOTES.md deviation 1).

The gold is: execute the candidate's SQL against a deterministically seeded
in-memory SQLite database and compare its result table, row by row and in
order, against the executed pinned reference query. Amounts are integer cents
so equality is exact. The prompts pin the schema, the output columns, their
order, and the row ordering, so ordered comparison is fair.

Authoring discipline: this module is gold-only. proxy_bank.py re-implements
its own independent SQL substrate and must not import from here.
"""

from __future__ import annotations

import random
import re
import sqlite3
from typing import Optional

GOLD_SEED = 1729
N_CUSTOMERS = 40
TIERS = ("free", "pro", "enterprise")

DDL = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    signup_tier TEXT NOT NULL CHECK (signup_tier IN ('free', 'pro', 'enterprise'))
);

CREATE TABLE payments (
    payment_id   INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    type         TEXT NOT NULL CHECK (type IN ('charge', 'refund')),
    paid_at      TEXT NOT NULL
);
"""


def _generate_rows(seed: int = GOLD_SEED) -> tuple[list[tuple], list[tuple]]:
    rng = random.Random(seed)
    customers = []
    payments = []
    payment_id = 1
    for cid in range(1, N_CUSTOMERS + 1):
        tier = TIERS[rng.randrange(3)]
        customers.append((cid, f"Customer {cid:02d}", f"c{cid:02d}@example.com", tier))
        # Two customers with zero payments: join-type choices become observable
        # surface features that do NOT flip the top-10 verdict (DESIGN_NOTES).
        if cid in (7, 23):
            continue
        n_charges = rng.randint(2, 12)
        charge_amounts = []
        for _ in range(n_charges):
            amount = rng.randint(1_000, 50_000)  # $10.00 - $500.00
            day = rng.randint(0, 729)
            date = f"2024-01-01 +{day}d"
            payments.append((payment_id, cid, amount, "charge", _date(day)))
            charge_amounts.append(amount)
            payment_id += 1
        if rng.random() < 0.45:  # ~45% of paying customers have refunds
            for _ in range(rng.randint(1, 3)):
                base = rng.choice(charge_amounts)
                amount = rng.randint(1, base)
                day = rng.randint(0, 729)
                payments.append((payment_id, cid, amount, "refund", _date(day)))
                payment_id += 1
    return customers, payments


def _date(day_offset: int) -> str:
    # Deterministic pseudo-dates; only ordering/formatting matter, not calendars.
    month = 1 + (day_offset // 61) % 12
    day = 1 + day_offset % 28
    year = 2024 + (day_offset // 366)
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    customers, payments = _generate_rows()
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)
    conn.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?)", payments)
    conn.commit()
    return conn


REFERENCE_QUERIES = {
    "sql_ltv_top10": """
-- Top 10 customers by lifetime value (charges minus refunds), in cents.
SELECT c.customer_id,
       c.name,
       COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)
     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)
         AS lifetime_value_cents
FROM customers c
LEFT JOIN payments p ON p.customer_id = c.customer_id
GROUP BY c.customer_id, c.name
ORDER BY lifetime_value_cents DESC
LIMIT 10;
""".strip(),
    "sql_revenue_by_tier": """
-- Net revenue (charges minus refunds) per signup tier, highest first.
SELECT c.signup_tier,
       COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)
     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)
         AS net_revenue_cents
FROM customers c
LEFT JOIN payments p ON p.customer_id = c.customer_id
GROUP BY c.signup_tier
ORDER BY net_revenue_cents DESC;
""".strip(),
}

_PROMPT_COMMON = f"""You are given a SQLite database with exactly this schema and pre-seeded data:

```sql
{DDL.strip()}
```

Every payment is either a 'charge' or a 'refund'; refunds are stored as positive
amount_cents with type = 'refund'. Some customers have no payments at all.

Write ONE SQLite-compatible SELECT query, in a single ```sql fenced code block."""

TASK_PROMPTS = {
    "sql_ltv_top10": _PROMPT_COMMON
    + """

The query must return the top 10 customers by lifetime value, where lifetime
value = total charge cents minus total refund cents (customers with no payments
count as 0). Return exactly these columns, in this order:
customer_id, name, lifetime_value_cents — ordered by lifetime_value_cents
descending, limited to 10 rows.""",
    "sql_revenue_by_tier": _PROMPT_COMMON
    + """

The query must return net revenue per signup tier, where net revenue = total
charge cents minus total refund cents across all customers in that tier.
Return exactly these columns, in this order: signup_tier, net_revenue_cents —
one row per tier, ordered by net_revenue_cents descending.""",
}

_SQL_FENCE = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> Optional[str]:
    """Last ```sql fenced block, else the raw text if it looks like a query."""
    blocks = _SQL_FENCE.findall(text)
    if blocks:
        return blocks[-1].strip()
    stripped = text.strip()
    if re.match(r"(?is)^\s*(with|select)\b", stripped):
        return stripped
    return None


def run_query(conn: sqlite3.Connection, sql: str) -> list[tuple]:
    cur = conn.execute(sql)
    return [tuple(row) for row in cur.fetchall()]


def reference_result(task_id: str) -> list[tuple]:
    conn = build_db()
    try:
        return run_query(conn, REFERENCE_QUERIES[task_id])
    finally:
        conn.close()


def gold_verdict(task_id: str, output_text: str) -> tuple[bool, dict]:
    """Execute the candidate's SQL and compare, ordered, to the reference result."""
    expected = reference_result(task_id)
    sql = extract_sql(output_text)
    if sql is None:
        return False, {"reason": "no SQL query found in output"}
    if len(re.findall(r";", sql.strip().rstrip(";"))) > 0:
        return False, {"reason": "multiple statements; prompt requires one query"}
    conn = build_db()
    try:
        actual = run_query(conn, sql)
    except sqlite3.Error as exc:
        return False, {"reason": f"execution error: {exc}"}
    finally:
        conn.close()
    if actual == expected:
        return True, {"rows": len(actual)}
    return False, {
        "reason": "result mismatch",
        "expected_rows": len(expected),
        "actual_rows": len(actual),
        "first_diff": _first_diff(expected, actual),
    }


def _first_diff(expected: list[tuple], actual: list[tuple]) -> str:
    for i in range(max(len(expected), len(actual))):
        e = expected[i] if i < len(expected) else "<missing>"
        a = actual[i] if i < len(actual) else "<missing>"
        if e != a:
            return f"row {i}: expected {e!r}, got {a!r}"
    return "<none>"


def sanity_check() -> None:
    """Gold self-checks (spec section 9: spot-check the gold before trusting it)."""
    for task_id in REFERENCE_QUERIES:
        rows = reference_result(task_id)
        assert rows, f"{task_id}: reference query returned no rows"
        values = [r[-1] for r in rows]
        assert values == sorted(values, reverse=True), f"{task_id}: not ordered DESC"
        assert len(set(values)) == len(values), (
            f"{task_id}: tied values — ordering would be ambiguous; reseed"
        )
    top10 = reference_result("sql_ltv_top10")
    assert len(top10) == 10
    assert all(len(r) == 3 for r in top10)
    tiers = reference_result("sql_revenue_by_tier")
    assert len(tiers) == 3


if __name__ == "__main__":
    sanity_check()
    print("sql_gold sanity checks passed")
    for tid in REFERENCE_QUERIES:
        print(tid, reference_result(tid)[:3])
