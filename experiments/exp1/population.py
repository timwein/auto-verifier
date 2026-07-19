"""Output populations (SPEC.md section 3).

Per task: the reference output (known-correct anchor), deterministic mutations
of the reference with a recorded name and an expected effect (break or
preserve correctness — the hypothesis is asserted against the gold in tests),
and hand-authored full outputs of varied quality standing in for `sampled`
outputs (DESIGN_NOTES.md deviation 4 — true sampling needs an API key; with
--sample the orchestrator generates real ones and appends them).

Mutations are the discriminating mechanism (spec section 3): breaking
mutations flip correctness while leaving surface features (ORDER BY clauses,
required arrays, code shape) intact — exactly what a confounded proxy misses.
Preserving mutations change surface form without changing correctness —
exactly what a confounded proxy wrongly punishes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import gold
from .gold import csv_gold, schema_gold
from .models import GroundedTask, Origin, Output


@dataclass(frozen=True)
class Mutation:
    name: str
    old: str
    new: str
    expected: str  # 'break' | 'preserve' — author hypothesis, asserted in tests
    # Some mutations need a second coordinated replacement (e.g. defeating a
    # guard that exists in two places); each pair must change the text.
    extra_pairs: tuple = ()


def _apply(reference: str, mutation: Mutation) -> str:
    mutated = reference
    for old, new in ((mutation.old, mutation.new), *mutation.extra_pairs):
        replaced = mutated.replace(old, new)
        if replaced == mutated:
            raise ValueError(f"mutation {mutation.name!r}: {old[:40]!r} not found")
        mutated = replaced
    return mutated


# ---------------------------------------------------------------------------
# SQL mutations (applied to the fenced reference output text)
# ---------------------------------------------------------------------------

SQL_LTV_MUTATIONS = [
    Mutation("asc_order", "DESC\nLIMIT 10", "ASC\nLIMIT 10", "break"),
    Mutation("limit_5", "LIMIT 10", "LIMIT 5", "break"),
    Mutation(
        "ignores_refunds_sign",
        "COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)",
        "COALESCE(SUM(p.amount_cents), 0)",
        "break",
    ),
    Mutation(
        "swap_charge_refund",
        "CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'refund'",
        "CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'charge'",
        "break",
    ),
    Mutation(
        "wrong_join_key",
        "ON p.customer_id = c.customer_id",
        "ON p.payment_id = c.customer_id",
        "break",
    ),
    Mutation(
        "count_not_sum",
        "COALESCE(SUM(CASE WHEN p.type = 'charge'",
        "COALESCE(COUNT(CASE WHEN p.type = 'charge'",
        "break",
    ),
    Mutation("drop_order_by", "\nORDER BY lifetime_value_cents DESC", "", "break"),
    Mutation("charges_dollars", "AS lifetime_value_cents", "/ 100.0 AS lifetime_value_cents", "break"),
    Mutation("lowercase_keywords", "SELECT c.customer_id", "select c.customer_id", "preserve"),
    Mutation(
        "no_comment",
        "-- Top 10 customers by lifetime value (charges minus refunds), in cents.\n",
        "",
        "preserve",
    ),
    Mutation("inner_join", "LEFT JOIN payments", "INNER JOIN payments", "preserve"),
    Mutation(
        "no_group_by_name",
        "GROUP BY c.customer_id, c.name",
        "GROUP BY c.customer_id",
        "preserve",  # SQLite permits the bare column; grouping key is the PK
    ),
    Mutation(
        "no_coalesce",
        "COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)",
        "SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END)\n"
        "     - SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END)",
        # Breaks, subtly: customers with charges but no refunds get
        # charges - NULL = NULL lifetime value and vanish from the top 10.
        # Surface-identical to the reference otherwise — prime confound bait.
        "break",
    ),
]

SQL_TIER_MUTATIONS = [
    Mutation("asc_order", "DESC;", "ASC;", "break"),
    Mutation(
        "charges_only",
        "COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)",
        "COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)",
        "break",
    ),
    Mutation(
        "swap_charge_refund",
        "CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'refund'",
        "CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'charge'",
        "break",
    ),
    Mutation(
        "group_by_customer",
        "GROUP BY c.signup_tier",
        "GROUP BY c.customer_id",
        "break",
    ),
    Mutation(
        "count_not_sum",
        "COALESCE(SUM(CASE WHEN p.type = 'charge'",
        "COALESCE(COUNT(CASE WHEN p.type = 'charge'",
        "break",
    ),
    Mutation("wrong_join_key", "ON p.customer_id = c.customer_id", "ON p.payment_id = c.customer_id", "break"),
    Mutation("lowercase_keywords", "SELECT c.signup_tier", "select c.signup_tier", "preserve"),
    Mutation(
        "no_comment",
        "-- Net revenue (charges minus refunds) per signup tier, highest first.\n",
        "",
        "preserve",
    ),
    Mutation("inner_join", "LEFT JOIN payments", "INNER JOIN payments", "preserve"),
    Mutation(
        "no_coalesce",
        "COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)\n"
        "     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)",
        "SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END)\n"
        "     - SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END)",
        "preserve",  # every tier has charges, so the sums are never NULL
    ),
]

# ---------------------------------------------------------------------------
# Schema mutations (applied to the schema dict, then re-serialized)
# ---------------------------------------------------------------------------


def _schema_variant(name: str, transform, expected: str):
    def build() -> str:
        schema = json.loads(json.dumps(schema_gold.REFERENCE_SCHEMA))
        transform(schema)
        return "```json\n" + json.dumps(schema, indent=2) + "\n```"

    return name, build, expected


def _drop_required(schema, field):
    schema["required"].remove(field)


SCHEMA_MUTATIONS = [
    _schema_variant("tenant_optional", lambda s: _drop_required(s, "tenant_id"), "break"),
    _schema_variant(
        "seats_min_zero",
        lambda s: s["properties"]["seats"].update(minimum=0),
        "break",
    ),
    _schema_variant(
        "extra_status_allowed",
        lambda s: s["properties"]["status"]["enum"].append("paused"),
        "break",
    ),
    _schema_variant(
        "additional_props_allowed",
        lambda s: s.update(additionalProperties=True),
        "break",
    ),
    _schema_variant(
        "seats_number_type",
        lambda s: s["properties"]["seats"].update(type="number"),
        "break",
    ),
    _schema_variant(
        "quantity_unbounded",
        lambda s: s["properties"]["usage_records"]["items"]["properties"][
            "quantity"
        ].pop("minimum"),
        "break",
    ),
    _schema_variant(
        "plan_units_optional",
        lambda s: s["properties"]["plan"]["required"].remove("included_usage_units"),
        "break",
    ),
    _schema_variant(
        "tenant_no_minlength",
        lambda s: s["properties"]["tenant_id"].pop("minLength"),
        "break",
    ),
    _schema_variant(
        "sorted_keys",
        lambda s: None,  # serialization change only
        "preserve",
    ),
    _schema_variant(
        "with_annotations",
        lambda s: (
            s["properties"]["seats"].update(description="Number of purchased seats"),
            s["properties"]["plan"].update(title="Plan"),
        ),
        "preserve",
    ),
    _schema_variant(
        "no_schema_key",
        lambda s: s.pop("$schema"),
        "preserve",
    ),
]


def _build_schema_mutation(name: str, build, expected: str) -> str:
    text = build()
    if name == "sorted_keys":
        schema = json.loads(json.dumps(schema_gold.REFERENCE_SCHEMA))
        text = "```json\n" + json.dumps(schema, indent=1, sort_keys=True) + "\n```"
    if text == schema_gold.REFERENCE_OUTPUT:
        raise ValueError(f"schema mutation {name!r} did not change the output")
    return text


# ---------------------------------------------------------------------------
# CSV mutations (applied to the fenced reference code text)
# ---------------------------------------------------------------------------

CSV_MUTATIONS = [
    Mutation(
        "no_strip",
        'row.append(raw if was_quoted else raw.strip(" \\t"))',
        "row.append(raw)",
        "break",
    ),
    Mutation(
        "tab_preference",
        'counts = [(line.count(","), ","), (line.count(";"), ";"),\n'
        '                      (line.count("\\t"), "\\t")]',
        'counts = [(line.count("\\t"), "\\t"), (line.count(";"), ";"),\n'
        '                      (line.count(","), ",")]',
        "break",  # tie-break order flips on the tie_prefers_comma fixture
    ),
    Mutation(
        "no_quote_escape",
        "if i + 1 < n and text[i + 1] == '\"':",
        "if False:",
        "break",
    ),
    Mutation(
        "keeps_blank_rows",
        # Blank lines are filtered both at the newline check and in end_row;
        # defeat both guards so whitespace-only rows come through as [""].
        'if row_started or "".join(field_chars).strip(" \\t") != "":\n'
        "                end_row()\n"
        "            else:\n"
        "                field_chars = []",
        "end_row()",
        "break",
        extra_pairs=(
            ('if any(f != "" for f in row) or len(row) > 1:', "if True:"),
        ),
    ),
    Mutation(
        "quote_whitespace_kept",
        'if was_quoted and ch in " \\t":\n'
        "            i += 1  # rule 3: whitespace between closing quote and delimiter\n"
        "            continue\n"
        "        ",
        "",
        "break",  # whitespace after a closing quote leaks into the field
    ),
    Mutation("renamed_buffer", "field_chars", "buf_chars", "preserve"),
    Mutation(
        "no_docstring",
        '    """Parse messy CSV per the pinned contract: delimiter detection on the\n'
        '    first non-empty line, double-quote fields with "" escapes, stripping of\n'
        '    unquoted fields, whitespace-only lines skipped."""\n',
        "",
        "preserve",
    ),
    Mutation(
        "extra_comment",
        "    # --- delimiter detection (rule 1) ---",
        "    # --- delimiter detection (rule 1) ---\n    # NOTE: raw counts on the first non-empty line only.",
        "preserve",
    ),
    Mutation("bare_strip", 'raw.strip(" \\t")', "raw.strip()", "preserve"),
]

# ---------------------------------------------------------------------------
# Hand-authored `sampled` stand-ins (offline mode). Each is a full output of
# varied quality and surface form; correctness is decided by the gold at build
# time. See DESIGN_NOTES.md deviation 4.
# ---------------------------------------------------------------------------

SAMPLED_STANDINS: dict[str, list[str]] = {
    "sql_ltv_top10": [
        # Correct: CTE form with prose around it.
        """Here is a query using CTEs for clarity:

```sql
WITH per_customer AS (
    SELECT c.customer_id,
           c.name,
           COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents ELSE 0 END), 0)
         - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents ELSE 0 END), 0)
             AS lifetime_value_cents
    FROM customers c
    LEFT JOIN payments p ON p.customer_id = c.customer_id
    GROUP BY c.customer_id, c.name
)
SELECT customer_id, name, lifetime_value_cents
FROM per_customer
ORDER BY lifetime_value_cents DESC
LIMIT 10;
```

The CTE computes each customer's net lifetime value, then we rank and keep 10.""",
        # Correct: compact lowercase subquery form.
        """```sql
select c.customer_id, c.name,
       coalesce((select sum(p.amount_cents) from payments p
                 where p.customer_id = c.customer_id and p.type = 'charge'), 0)
     - coalesce((select sum(p.amount_cents) from payments p
                 where p.customer_id = c.customer_id and p.type = 'refund'), 0)
       as lifetime_value_cents
from customers c
order by lifetime_value_cents desc
limit 10;
```""",
        # Wrong but surface-perfect: forgets refunds entirely, has every clause
        # a confounded proxy looks for (CTE, ORDER BY ... DESC, LIMIT 10).
        """```sql
-- Top 10 customers by lifetime value
WITH customer_ltv AS (
    SELECT c.customer_id,
           c.name,
           COALESCE(SUM(p.amount_cents), 0) AS lifetime_value_cents
    FROM customers c
    LEFT JOIN payments p ON p.customer_id = c.customer_id
    GROUP BY c.customer_id, c.name
)
SELECT customer_id, name, lifetime_value_cents
FROM customer_ltv
ORDER BY lifetime_value_cents DESC
LIMIT 10;
```""",
        # Wrong: averages instead of sums, otherwise plausible.
        """```sql
SELECT c.customer_id,
       c.name,
       CAST(AVG(CASE WHEN p.type = 'charge' THEN p.amount_cents ELSE 0 END) AS INTEGER)
           AS lifetime_value_cents
FROM customers c
LEFT JOIN payments p ON p.customer_id = c.customer_id
GROUP BY c.customer_id, c.name
ORDER BY lifetime_value_cents DESC
LIMIT 10;
```""",
        # Wrong: extra column and wrong order of columns.
        """```sql
SELECT c.name,
       c.customer_id,
       c.email,
       COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)
     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)
         AS lifetime_value_cents
FROM customers c
LEFT JOIN payments p ON p.customer_id = c.customer_id
GROUP BY c.customer_id, c.name, c.email
ORDER BY lifetime_value_cents DESC
LIMIT 10;
```""",
        # Correct but scruffy: one line, no comments, ugly aliases.
        "```sql\nSELECT t1.customer_id, t1.name, COALESCE(SUM(CASE WHEN t2.type = 'charge' THEN t2.amount_cents END), 0) - COALESCE(SUM(CASE WHEN t2.type = 'refund' THEN t2.amount_cents END), 0) AS lifetime_value_cents FROM customers t1 LEFT JOIN payments t2 ON t2.customer_id = t1.customer_id GROUP BY t1.customer_id, t1.name ORDER BY lifetime_value_cents DESC LIMIT 10;\n```",
    ],
    "sql_revenue_by_tier": [
        # Correct: CTE form.
        """```sql
WITH tier_revenue AS (
    SELECT c.signup_tier,
           COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents ELSE 0 END), 0)
         - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents ELSE 0 END), 0)
             AS net_revenue_cents
    FROM customers c
    LEFT JOIN payments p ON p.customer_id = c.customer_id
    GROUP BY c.signup_tier
)
SELECT signup_tier, net_revenue_cents
FROM tier_revenue
ORDER BY net_revenue_cents DESC;
```""",
        # Wrong but surface-plausible: joins on tier of *payments' customers*
        # via a fan-out-prone double join and double counts.
        """```sql
SELECT c.signup_tier,
       COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)
     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)
         AS net_revenue_cents
FROM customers c
JOIN customers c2 ON c2.signup_tier = c.signup_tier
LEFT JOIN payments p ON p.customer_id = c2.customer_id
GROUP BY c.signup_tier
ORDER BY net_revenue_cents DESC;
```""",
        # Wrong: gross revenue only, formatted nicely with the right clauses.
        """```sql
-- Revenue per tier
SELECT c.signup_tier,
       COALESCE(SUM(p.amount_cents), 0) AS net_revenue_cents
FROM customers c
LEFT JOIN payments p ON p.customer_id = c.customer_id
GROUP BY c.signup_tier
ORDER BY net_revenue_cents DESC;
```""",
        # Correct: lowercase, subquery per tier.
        """The following query returns one row per tier:

```sql
select t.signup_tier,
       (select coalesce(sum(case when p.type = 'charge' then p.amount_cents else 0 end), 0)
             - coalesce(sum(case when p.type = 'refund' then p.amount_cents else 0 end), 0)
        from payments p
        join customers c on c.customer_id = p.customer_id
        where c.signup_tier = t.signup_tier) as net_revenue_cents
from (select distinct signup_tier from customers) t
order by net_revenue_cents desc;
```""",
        # Wrong: ordered ascending, everything else right.
        """```sql
SELECT c.signup_tier,
       COALESCE(SUM(CASE WHEN p.type = 'charge' THEN p.amount_cents END), 0)
     - COALESCE(SUM(CASE WHEN p.type = 'refund' THEN p.amount_cents END), 0)
         AS net_revenue_cents
FROM customers c
LEFT JOIN payments p ON p.customer_id = c.customer_id
GROUP BY c.signup_tier
ORDER BY net_revenue_cents;
```""",
    ],
    "billing_schema": [
        # Correct: equivalent schema, different authoring style ($defs, annotations).
        "Here is the schema:\n\n```json\n"
        + json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "SaaS Billing Subscription",
                "description": "One subscription record for a multi-tenant billing system.",
                "type": "object",
                "$defs": {
                    "plan": {
                        "type": "object",
                        "required": [
                            "pricing_model",
                            "price_per_seat_cents",
                            "included_usage_units",
                        ],
                        "properties": {
                            "pricing_model": {"enum": ["seat", "usage", "hybrid"]},
                            "price_per_seat_cents": {"type": "integer", "minimum": 0},
                            "included_usage_units": {"type": "integer", "minimum": 0},
                        },
                    },
                    "usage_record": {
                        "type": "object",
                        "required": ["unit", "quantity"],
                        "properties": {
                            "unit": {"type": "string", "minLength": 1},
                            "quantity": {"type": "number", "minimum": 0},
                        },
                    },
                },
                "properties": {
                    "subscription_id": {"type": "string", "minLength": 1},
                    "tenant_id": {"type": "string", "minLength": 1},
                    "status": {"enum": ["trial", "active", "past_due", "canceled"]},
                    "seats": {"type": "integer", "minimum": 1},
                    "plan": {"$ref": "#/$defs/plan"},
                    "usage_records": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/usage_record"},
                    },
                },
                "required": [
                    "subscription_id",
                    "tenant_id",
                    "status",
                    "seats",
                    "plan",
                ],
                "additionalProperties": False,
            },
            indent=2,
        )
        + "\n```",
        # Wrong but surface-complete: forgets additionalProperties: false.
        "```json\n"
        + json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "Subscription",
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "minLength": 1},
                    "tenant_id": {"type": "string", "minLength": 1},
                    "status": {"enum": ["trial", "active", "past_due", "canceled"]},
                    "seats": {"type": "integer", "minimum": 1},
                    "plan": {
                        "type": "object",
                        "required": [
                            "pricing_model",
                            "price_per_seat_cents",
                            "included_usage_units",
                        ],
                        "properties": {
                            "pricing_model": {"enum": ["seat", "usage", "hybrid"]},
                            "price_per_seat_cents": {"type": "integer", "minimum": 0},
                            "included_usage_units": {"type": "integer", "minimum": 0},
                        },
                    },
                    "usage_records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["unit", "quantity"],
                            "properties": {
                                "unit": {"type": "string", "minLength": 1},
                                "quantity": {"type": "number", "minimum": 0},
                            },
                        },
                    },
                },
                "required": ["subscription_id", "tenant_id", "status", "seats", "plan"],
            },
            indent=2,
        )
        + "\n```",
        # Wrong: seats typed as string with a digits pattern.
        "```json\n"
        + json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "minLength": 1},
                    "tenant_id": {"type": "string", "minLength": 1},
                    "status": {"enum": ["trial", "active", "past_due", "canceled"]},
                    "seats": {"type": "string", "pattern": "^[1-9][0-9]*$"},
                    "plan": {
                        "type": "object",
                        "required": [
                            "pricing_model",
                            "price_per_seat_cents",
                            "included_usage_units",
                        ],
                        "properties": {
                            "pricing_model": {"enum": ["seat", "usage", "hybrid"]},
                            "price_per_seat_cents": {"type": "integer", "minimum": 0},
                            "included_usage_units": {"type": "integer", "minimum": 0},
                        },
                    },
                    "usage_records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["unit", "quantity"],
                            "properties": {
                                "unit": {"type": "string", "minLength": 1},
                                "quantity": {"type": "number", "minimum": 0},
                            },
                        },
                    },
                },
                "required": ["subscription_id", "tenant_id", "status", "seats", "plan"],
                "additionalProperties": False,
            },
            indent=2,
        )
        + "\n```",
        # Correct: compact serialization of an equivalent schema.
        "```json\n"
        + json.dumps(schema_gold.REFERENCE_SCHEMA, separators=(",", ":"))
        + "\n```",
        # Wrong: prose-heavy output whose schema marks usage_records required
        # (over-constrains: rejects valid records without usage_records).
        "The design uses one top-level object per subscription:\n\n```json\n"
        + json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "string", "minLength": 1},
                    "tenant_id": {"type": "string", "minLength": 1},
                    "status": {"enum": ["trial", "active", "past_due", "canceled"]},
                    "seats": {"type": "integer", "minimum": 1},
                    "plan": {
                        "type": "object",
                        "required": [
                            "pricing_model",
                            "price_per_seat_cents",
                            "included_usage_units",
                        ],
                        "properties": {
                            "pricing_model": {"enum": ["seat", "usage", "hybrid"]},
                            "price_per_seat_cents": {"type": "integer", "minimum": 0},
                            "included_usage_units": {"type": "integer", "minimum": 0},
                        },
                    },
                    "usage_records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["unit", "quantity"],
                            "properties": {
                                "unit": {"type": "string", "minLength": 1},
                                "quantity": {"type": "number", "minimum": 0},
                            },
                        },
                    },
                },
                "required": [
                    "subscription_id",
                    "tenant_id",
                    "status",
                    "seats",
                    "plan",
                    "usage_records",
                ],
                "additionalProperties": False,
            },
            indent=2,
        )
        + "\n```",
    ],
    "csv_parser": [
        # Wrong but plausible: splitlines + split, no quote awareness at all.
        """```python
def parse_csv(text: str) -> list[list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    first = lines[0]
    counts = [(first.count(","), ","), (first.count(";"), ";"), (first.count("\\t"), "\\t")]
    best = max(c for c, _ in counts)
    delimiter = ","
    if best > 0:
        for c, d in counts:
            if c == best:
                delimiter = d
                break
    return [[f.strip() for f in ln.split(delimiter)] for ln in lines]
```""",
        # Wrong: csv module — quote handling fine, but the stripping and
        # tie-break rules differ from the pinned contract.
        """```python
import csv
import io

def parse_csv(text: str) -> list[list[str]]:
    sample = text[:1024]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t")
    except csv.Error:
        class dialect(csv.excel):
            delimiter = ","
    rows = []
    for row in csv.reader(io.StringIO(text), dialect):
        if any(f.strip() for f in row):
            rows.append(row)
    return rows
```""",
        # Correct: independent implementation via a token scanner (verified
        # against the gold fixtures at build time).
        """```python
def parse_csv(text: str) -> list[list[str]]:
    # detect delimiter on the first non-empty line, ties: ',' > ';' > '\\t'
    delim = ","
    for line in text.split("\\n"):
        if line.strip():
            tallies = ((line.count(","), ","), (line.count(";"), ";"),
                       (line.count("\\t"), "\\t"))
            top = max(t[0] for t in tallies)
            if top:
                delim = next(d for c, d in tallies if c == top)
            break

    out: list[list[str]] = []
    cur: list[str] = []
    piece = ""
    quoted_piece = False
    quoting = False
    seen_any = False

    def flush_field():
        nonlocal piece, quoted_piece
        cur.append(piece if quoted_piece else piece.strip(" \\t"))
        piece = ""
        quoted_piece = False

    def flush_row():
        nonlocal cur, seen_any
        flush_field()
        if len(cur) > 1 or any(cur):
            out.append(cur)
        cur = []
        seen_any = False

    idx = 0
    while idx < len(text):
        ch = text[idx]
        if quoting:
            if ch == '"':
                if text[idx + 1:idx + 2] == '"':
                    piece += '"'
                    idx += 2
                    continue
                quoting = False
            else:
                piece += ch
            idx += 1
            continue
        if ch == '"' and piece.strip(" \\t") == "":
            piece = ""
            quoting = True
            quoted_piece = True
            seen_any = True
        elif ch == delim:
            flush_field()
            seen_any = True
        elif ch == "\\n":
            if seen_any or piece.strip(" \\t"):
                flush_row()
            else:
                piece = ""
        elif ch == "\\r":
            pass
        elif quoted_piece and ch in " \\t":
            pass
        else:
            piece += ch
            seen_any = seen_any or ch not in " \\t"
        idx += 1
    if seen_any or piece.strip(" \\t"):
        flush_row()
    return out
```""",
        # Wrong: handles quotes but forgets the "" escape and blank-line skip.
        """```python
def parse_csv(text: str) -> list[list[str]]:
    lines = text.splitlines()
    if not lines:
        return []
    first = next((ln for ln in lines if ln.strip()), "")
    counts = [(first.count(","), ","), (first.count(";"), ";"), (first.count("\\t"), "\\t")]
    best = max(c for c, _ in counts)
    delimiter = "," if best == 0 else next(d for c, d in counts if c == best)
    rows = []
    for line in lines:
        fields = []
        field = ""
        in_q = False
        for ch in line:
            if ch == '"':
                in_q = not in_q
            elif ch == delimiter and not in_q:
                fields.append(field.strip())
                field = ""
            else:
                field += ch
        fields.append(field.strip())
        rows.append(fields)
    return rows
```""",
    ],
}


def _mutated_outputs(task: GroundedTask, mutations: list[Mutation]) -> list[Output]:
    outputs = []
    for mut in mutations:
        text = _apply(task.reference_output, mut)
        outputs.append(
            Output(
                task_id=task.task_id,
                text=text,
                origin=Origin.MUTATED,
                gold_meta={"mutation": mut.name, "expected": mut.expected},
            )
        )
    return outputs


def _schema_mutated_outputs(task: GroundedTask) -> list[Output]:
    outputs = []
    for name, build, expected in SCHEMA_MUTATIONS:
        text = _build_schema_mutation(name, build, expected)
        outputs.append(
            Output(
                task_id=task.task_id,
                text=text,
                origin=Origin.MUTATED,
                gold_meta={"mutation": name, "expected": expected},
            )
        )
    return outputs


MUTATION_SETS = {
    "sql_ltv_top10": SQL_LTV_MUTATIONS,
    "sql_revenue_by_tier": SQL_TIER_MUTATIONS,
    "csv_parser": CSV_MUTATIONS,
}


def build_population(task: GroundedTask, include_sampled: bool = True) -> list[Output]:
    """Reference + mutated + sampled stand-ins, all gold-labeled."""
    outputs = [
        Output(
            task_id=task.task_id,
            text=task.reference_output,
            origin=Origin.REFERENCE,
            gold_meta={"provenance": "pinned reference"},
        )
    ]
    if task.task_id == "billing_schema":
        outputs.extend(_schema_mutated_outputs(task))
    else:
        outputs.extend(_mutated_outputs(task, MUTATION_SETS[task.task_id]))
    if include_sampled:
        for i, text in enumerate(SAMPLED_STANDINS.get(task.task_id, [])):
            outputs.append(
                Output(
                    task_id=task.task_id,
                    text=text,
                    origin=Origin.SAMPLED,
                    gold_meta={"provenance": "pre-authored stand-in", "index": i},
                )
            )
    for output in outputs:
        verdict, meta = gold.gold_verdict(task, output.text)
        output.gold_verdict = verdict
        output.gold_meta.update(gold_result=meta)
    return outputs


def balance_report(outputs: list[Output]) -> dict:
    n = len(outputs)
    passes = sum(1 for o in outputs if o.gold_verdict)
    return {
        "n": n,
        "pass": passes,
        "fail": n - passes,
        "pass_rate": round(passes / n, 3) if n else 0.0,
    }


BALANCE_BOUNDS = (0.25, 0.75)


def check_balance(task_id: str, outputs: list[Output]) -> dict:
    """Spec section 3/9: enforce pass/fail balance or the metrics are garbage."""
    report = balance_report(outputs)
    low, high = BALANCE_BOUNDS
    if not (low <= report["pass_rate"] <= high):
        raise RuntimeError(
            f"{task_id}: population pass rate {report['pass_rate']} outside "
            f"[{low}, {high}] — resample/mutate to fix (spec section 3)"
        )
    return report


def sample_real_outputs(task: GroundedTask, client, model: str, n: int = 6) -> list[Output]:
    """Keyed mode only: generate true sampled outputs at varied temperature."""
    temperatures = [0.0, 0.4, 0.7, 1.0, 1.0, 1.0][:n]
    outputs = []
    for i, temp in enumerate(temperatures):
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=temp,
            messages=[{"role": "user", "content": task.prompt}],
        )
        text = response.content[0].text
        output = Output(
            task_id=task.task_id,
            text=text,
            origin=Origin.SAMPLED,
            gold_meta={"provenance": "model-sampled", "temperature": temp, "index": i},
        )
        verdict, meta = gold.gold_verdict(task, text)
        output.gold_verdict = verdict
        output.gold_meta.update(gold_result=meta)
        outputs.append(output)
    return outputs


if __name__ == "__main__":
    for task in gold.build_tasks().values():
        pop = build_population(task)
        print(task.task_id, balance_report(pop))
        for o in pop:
            tag = o.gold_meta.get("mutation") or o.gold_meta.get("provenance")
            expected = o.gold_meta.get("expected")
            print(f"  {'PASS' if o.gold_verdict else 'FAIL'}  {o.origin.value:9s} {tag} "
                  + (f"(expected {expected})" if expected else ""))
