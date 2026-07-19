"""Gold verifier registry: task definitions + verdict dispatch.

Each GroundedTask's gold_verifier_ref names the module that implements its
deterministic check; gold_verdict() dispatches on it. proxy_bank.py must not
import anything from this package (enforced by a test).
"""

from __future__ import annotations

from ..models import GroundedTask
from . import csv_gold, schema_gold, sql_gold


def build_tasks() -> dict[str, GroundedTask]:
    tasks = {
        "sql_ltv_top10": GroundedTask(
            task_id="sql_ltv_top10",
            prompt=sql_gold.TASK_PROMPTS["sql_ltv_top10"],
            reference_output="```sql\n"
            + sql_gold.REFERENCE_QUERIES["sql_ltv_top10"]
            + "\n```",
            gold_verifier_ref="sql_gold",
        ),
        "sql_revenue_by_tier": GroundedTask(
            task_id="sql_revenue_by_tier",
            prompt=sql_gold.TASK_PROMPTS["sql_revenue_by_tier"],
            reference_output="```sql\n"
            + sql_gold.REFERENCE_QUERIES["sql_revenue_by_tier"]
            + "\n```",
            gold_verifier_ref="sql_gold",
        ),
        "billing_schema": GroundedTask(
            task_id="billing_schema",
            prompt=schema_gold.TASK_PROMPT,
            reference_output=schema_gold.REFERENCE_OUTPUT,
            gold_verifier_ref="schema_gold",
        ),
        "csv_parser": GroundedTask(
            task_id="csv_parser",
            prompt=csv_gold.TASK_PROMPT,
            reference_output=csv_gold.REFERENCE_OUTPUT,
            gold_verifier_ref="csv_gold",
        ),
    }
    return tasks


_DISPATCH = {
    "sql_gold": sql_gold.gold_verdict,
    "schema_gold": schema_gold.gold_verdict,
    "csv_gold": csv_gold.gold_verdict,
}


def gold_verdict(task: GroundedTask, output_text: str) -> tuple[bool, dict]:
    return _DISPATCH[task.gold_verifier_ref](task.task_id, output_text)


def sanity_check_all() -> None:
    """Spec section 9: the reference output of every task must pass its gold."""
    sql_gold.sanity_check()
    schema_gold.sanity_check()
    csv_gold.sanity_check()
    for task in build_tasks().values():
        ok, meta = gold_verdict(task, task.reference_output)
        assert ok, f"{task.task_id}: reference output fails gold: {meta}"
