#!/usr/bin/env python3
from __future__ import annotations
"""
Population builder for Experiment 1.

Per task, builds a labeled output population (target 30-60):
  * 1 reference anchor (known correct),
  * correctness-PRESERVING variants (expected pass), and
  * correctness-BREAKING mutations (expected fail), each recorded in gold_meta.

The gold verifier is then run over the whole population to assign gold_verdict;
we never trust the "expected" label, we report what the gold actually says and
the pass/fail balance (spec section 3 + section 9 "population must span the spectrum").

`sampled` outputs (model generations at varied temperature) are added only in real
(non-mock) mode when an Anthropic client is available; they are a minority by design.
"""

import json
from typing import Callable, Optional

from .models import Output, Origin, GroundedTask
from .gold import sql_gold as SG
from .gold import schema_gold as JG


# ---------------------------------------------------------------------------
# Task registry (wraps the gold specs into GroundedTask objects)
# ---------------------------------------------------------------------------

def all_tasks() -> dict[str, GroundedTask]:
    tasks: dict[str, GroundedTask] = {}
    for tid, spec in SG.SQL_TASKS.items():
        tasks[tid] = GroundedTask(
            task_id=tid, prompt=spec.prompt,
            reference_output=SG.reference_output(tid),
            family="sql", gold_verifier_ref=f"sql_gold.gold_verdict::{tid}",
            fixtures={"reference_query": spec.reference_query, "ordered": spec.ordered},
        )
    for tid, spec in JG.SCHEMA_TASKS.items():
        tasks[tid] = GroundedTask(
            task_id=tid, prompt=spec.prompt,
            reference_output=JG.reference_output(tid),
            family="schema", gold_verifier_ref=f"schema_gold.gold_verdict::{tid}",
            fixtures={"reference_schema": spec.reference_schema,
                      "n_instances": len(spec.instances)},
        )
    return tasks


def gold_for(task: GroundedTask) -> Callable[[str], float]:
    if task.family == "sql":
        return lambda text: SG.gold_verdict(task.task_id, text)
    return lambda text: JG.gold_verdict(task.task_id, text)


# ---------------------------------------------------------------------------
# SQL variant/mutation generators (string transforms on the reference query)
# ---------------------------------------------------------------------------

def _sql_wrap(q: str) -> str:
    return f"```sql\n{q};\n```"


def _sql_variants(tid: str) -> list[tuple[str, str, str]]:
    """Return list of (mutation_name, expected, output_text)."""
    q = SG.SQL_TASKS[tid].reference_query
    out: list[tuple[str, str, str]] = []

    # --- correctness-preserving (expected pass) ---
    out.append(("alias_rename", "pass",
                _sql_wrap(q.replace(" c ", " cust ").replace("c.", "cust.")
                          .replace(" o ", " ord ").replace("o.", "ord."))))
    out.append(("explicit_inner_join", "pass", _sql_wrap(q.replace("JOIN", "INNER JOIN"))))
    out.append(("status_not_refunded", "pass",
                _sql_wrap(q.replace("o.status = 'paid'", "o.status <> 'refunded'"))))
    out.append(("with_comment", "pass", "```sql\n-- top results\n" + q + ";\n```"))
    out.append(("col_alias_rename", "pass",
                _sql_wrap(q.replace(" AS ltv", " AS lifetime_value")
                          .replace("ORDER BY ltv", "ORDER BY lifetime_value")
                          .replace(" AS net_revenue", " AS revenue"))))
    out.append(("whitespace_reflow", "pass",
                "```sql\n" + q.replace(" FROM", "\nFROM").replace(" WHERE", "\nWHERE")
                .replace(" GROUP BY", "\nGROUP BY").replace(" ORDER BY", "\nORDER BY") + ";\n```"))
    out.append(("uppercase_status", "pass",
                _sql_wrap(q.replace("= 'paid'", "IN ('paid')"))))

    # --- correctness-breaking (expected fail) ---
    out.append(("drop_refund_filter", "fail",
                _sql_wrap(q.replace("WHERE o.status = 'paid' ", ""))))
    out.append(("only_refunded", "fail",
                _sql_wrap(q.replace("'paid'", "'refunded'"))))
    out.append(("avg_not_sum", "fail", _sql_wrap(q.replace("SUM(", "AVG("))))
    out.append(("count_not_sum", "fail",
                _sql_wrap(q.replace("SUM(o.amount_cents)", "COUNT(o.amount_cents)"))))
    out.append(("wrong_join_key", "fail",
                _sql_wrap(q.replace("c.customer_id = o.customer_id",
                                    "c.customer_id = o.order_id"))))

    if SG.SQL_TASKS[tid].ordered:  # ranking-specific breakages
        out.append(("desc_to_asc", "fail", _sql_wrap(q.replace("DESC", "ASC"))))
        out.append(("drop_order_by", "fail",
                    _sql_wrap(q.replace(" ORDER BY ltv DESC", ""))))
        out.append(("limit_5", "fail", _sql_wrap(q.replace("LIMIT 10", "LIMIT 5"))))
        out.append(("limit_20", "fail", _sql_wrap(q.replace("LIMIT 10", "LIMIT 20"))))
    else:  # grouping-specific breakages
        out.append(("group_by_name", "fail",
                    _sql_wrap(q.replace("GROUP BY c.tier", "GROUP BY c.name"))))
        out.append(("no_group_by", "fail",
                    _sql_wrap(q.replace("c.tier, ", "").replace(" GROUP BY c.tier", ""))))

    out.append(("broken_syntax", "fail", "```sql\nSELEKT * FROM custmers\n```"))
    return out


# ---------------------------------------------------------------------------
# Schema variant/mutation generators
# ---------------------------------------------------------------------------

def _schema_wrap(d: dict) -> str:
    return "```json\n" + json.dumps(d, indent=2) + "\n```"


def _deep(d: dict) -> dict:
    return json.loads(json.dumps(d))


def _schema_variants(tid: str) -> list[tuple[str, str, str]]:
    base = JG.SCHEMA_TASKS[tid].reference_schema
    out: list[tuple[str, str, str]] = []

    # --- correctness-preserving (expected pass) ---
    v = _deep(base); v["title"] = "Record"; out.append(("add_title", "pass", _schema_wrap(v)))
    v = _deep(base); v["description"] = "A record."; out.append(("add_description", "pass", _schema_wrap(v)))
    v = _deep(base); v["$id"] = "https://example.com/s.json"; out.append(("add_id", "pass", _schema_wrap(v)))
    v = _deep(base); v["required"] = list(reversed(v["required"])); out.append(("reorder_required", "pass", _schema_wrap(v)))
    v = _deep(base); v["properties"] = dict(reversed(list(v["properties"].items()))); out.append(("reorder_props", "pass", _schema_wrap(v)))
    # add an explicitly-typed optional property not present in any instance (still valid)
    v = _deep(base); v["properties"]["notes"] = {"type": "string"}; out.append(("add_optional_prop", "pass", _schema_wrap(v)))

    # --- correctness-breaking (expected fail) ---
    v = _deep(base); v.pop("required", None); out.append(("drop_required", "fail", _schema_wrap(v)))
    v = _deep(base); v["additionalProperties"] = True; out.append(("allow_additional", "fail", _schema_wrap(v)))
    v = _deep(base); v.pop("additionalProperties", None); out.append(("remove_addprop_constraint", "fail", _schema_wrap(v)))

    props = list(base["properties"].keys())
    # drop a required field's constraints / the field entirely
    req = base["required"]
    v = _deep(base); v["required"] = req[1:]; out.append(("shrink_required", "fail", _schema_wrap(v)))

    # loosen enum / pattern / minimum / type depending on family
    if tid == "billing_schema":
        v = _deep(base); v["properties"]["plan"].pop("enum", None); out.append(("drop_plan_enum", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["currency"].pop("pattern", None); out.append(("drop_currency_pattern", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["amount_cents"].pop("minimum", None); out.append(("drop_amount_min", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["amount_cents"]["type"] = ["integer", "string"]; out.append(("widen_amount_type", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["seats"].pop("minimum", None); out.append(("drop_seats_min", "fail", _schema_wrap(v)))
        v = _deep(base); del v["properties"]["seats"]; out.append(("remove_seats_prop", "fail", _schema_wrap(v)))
    else:  # event_schema
        v = _deep(base); v["properties"]["type"].pop("enum", None); out.append(("drop_type_enum", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["event_id"].pop("pattern", None); out.append(("drop_id_pattern", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["created_at"].pop("minimum", None); out.append(("drop_created_min", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["data"]["type"] = ["object", "array"]; out.append(("widen_data_type", "fail", _schema_wrap(v)))
        v = _deep(base); v["properties"]["livemode"]["type"] = ["boolean", "string"]; out.append(("widen_livemode_type", "fail", _schema_wrap(v)))
        v = _deep(base); del v["properties"]["livemode"]; out.append(("remove_livemode_prop", "fail", _schema_wrap(v)))

    out.append(("not_json", "fail", "```json\n{ this is not valid json }\n```"))
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_population(task: GroundedTask, smoke: bool = False) -> list[Output]:
    """Build the labeled output population for a task and run the gold over it."""
    gold = gold_for(task)
    variants = _sql_variants(task.task_id) if task.family == "sql" else _schema_variants(task.task_id)
    if smoke:
        # 1 ref + 2 expected-fail + 2 expected-pass
        fails = [v for v in variants if v[1] == "fail"][:2]
        passes = [v for v in variants if v[1] == "pass"][:2]
        variants = passes + fails

    outputs: list[Output] = []
    ref = Output(task_id=task.task_id, text=task.reference_output,
                 origin=Origin.REFERENCE, output_id=f"{task.task_id}::reference")
    ref.gold_verdict = gold(ref.text)
    ref.gold_meta = {"mutation": None, "expected": "pass"}
    outputs.append(ref)

    for name, expected, text in variants:
        o = Output(task_id=task.task_id, text=text, origin=Origin.MUTATED,
                   output_id=f"{task.task_id}::{name}")
        o.gold_verdict = gold(text)
        o.gold_meta = {"mutation": name, "expected": expected,
                       "agrees_with_expected": (expected == "pass") == (o.gold_verdict >= 0.5)}
        outputs.append(o)
    return outputs


def balance(outputs: list[Output]) -> dict:
    n = len(outputs)
    n_pass = sum(1 for o in outputs if (o.gold_verdict or 0) >= 0.5)
    return {"n": n, "n_pass": n_pass, "n_fail": n - n_pass,
            "pass_frac": round(n_pass / n, 3) if n else 0.0}
