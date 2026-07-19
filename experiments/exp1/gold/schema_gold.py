"""Executable gold for the billing_schema task (DESIGN_NOTES.md deviation 1).

The gold is: the candidate output must contain a valid JSON Schema
(draft 2020-12) that accepts every held-out valid instance and rejects every
held-out invalid instance. The prompt pins the exact contract so a fixed
battery is fair; every battery instance maps to a specific contract clause.

Authoring discipline: gold-only module. proxy_bank.py builds its own,
independent (smaller) instance battery and must not import from here.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import jsonschema
from jsonschema import Draft202012Validator

TASK_PROMPT = """Design a JSON Schema (draft 2020-12) for one 'subscription' record of a
multi-tenant SaaS billing system supporting seat-based and usage-based pricing.

The schema must enforce exactly this contract:

- The record is an object with required fields: subscription_id, tenant_id,
  status, seats, plan. No other top-level fields are allowed.
- Optional top-level field: usage_records.
- subscription_id and tenant_id: non-empty strings.
- status: one of "trial", "active", "past_due", "canceled".
- seats: an integer, minimum 1 (no fractional seats).
- plan: an object with required fields pricing_model, price_per_seat_cents,
  included_usage_units:
    - pricing_model: one of "seat", "usage", "hybrid".
    - price_per_seat_cents: an integer, minimum 0.
    - included_usage_units: an integer, minimum 0.
- usage_records: an array of objects, each with required fields unit
  (non-empty string) and quantity (a number, minimum 0).

Output the schema as a single ```json fenced code block."""

REFERENCE_SCHEMA: dict = {
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
            "properties": {
                "pricing_model": {"enum": ["seat", "usage", "hybrid"]},
                "price_per_seat_cents": {"type": "integer", "minimum": 0},
                "included_usage_units": {"type": "integer", "minimum": 0},
            },
            "required": [
                "pricing_model",
                "price_per_seat_cents",
                "included_usage_units",
            ],
        },
        "usage_records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "unit": {"type": "string", "minLength": 1},
                    "quantity": {"type": "number", "minimum": 0},
                },
                "required": ["unit", "quantity"],
            },
        },
    },
    "required": ["subscription_id", "tenant_id", "status", "seats", "plan"],
    "additionalProperties": False,
}

REFERENCE_OUTPUT = "```json\n" + json.dumps(REFERENCE_SCHEMA, indent=2) + "\n```"

_PLAN = {
    "pricing_model": "hybrid",
    "price_per_seat_cents": 1500,
    "included_usage_units": 1000,
}


def _sub(**overrides) -> dict:
    base = {
        "subscription_id": "sub_001",
        "tenant_id": "ten_001",
        "status": "active",
        "seats": 5,
        "plan": dict(_PLAN),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not _OMIT}


_OMIT = object()

# Held-out battery. Label -> (instance, is_valid). Every clause of the pinned
# contract is exercised by at least one instance in each direction where
# meaningful; tests assert every breaking mutation is caught by the battery.
INSTANCES: dict[str, tuple[dict, bool]] = {
    "minimal_valid": (_sub(), True),
    "trial_valid": (_sub(status="trial", seats=1), True),
    "usage_plan_valid": (
        _sub(plan={"pricing_model": "usage", "price_per_seat_cents": 0,
                   "included_usage_units": 0}),
        True,
    ),
    "with_usage_records_valid": (
        _sub(usage_records=[{"unit": "api_calls", "quantity": 1234.5}]),
        True,
    ),
    "empty_usage_records_valid": (_sub(usage_records=[]), True),
    "canceled_valid": (_sub(status="canceled", seats=250), True),
    "past_due_valid": (_sub(status="past_due"), True),
    "seat_plan_valid": (
        _sub(plan={"pricing_model": "seat", "price_per_seat_cents": 900,
                   "included_usage_units": 0}),
        True,
    ),
    "missing_tenant_id": (_sub(tenant_id=_OMIT), False),
    "missing_plan": (_sub(plan=_OMIT), False),
    "bad_status": (_sub(status="paused"), False),
    "zero_seats": (_sub(seats=0), False),
    "string_seats": (_sub(seats="5"), False),
    "fractional_seats": (_sub(seats=2.5), False),
    "bad_pricing_model": (
        _sub(plan={"pricing_model": "flat", "price_per_seat_cents": 1500,
                   "included_usage_units": 0}),
        False,
    ),
    "negative_seat_price": (
        _sub(plan={"pricing_model": "seat", "price_per_seat_cents": -1,
                   "included_usage_units": 0}),
        False,
    ),
    "plan_missing_included_units": (
        _sub(plan={"pricing_model": "seat", "price_per_seat_cents": 1500}),
        False,
    ),
    "extra_top_level_field": (_sub(discount_pct=10), False),
    "negative_usage_quantity": (
        _sub(usage_records=[{"unit": "api_calls", "quantity": -1}]),
        False,
    ),
    "usage_record_missing_unit": (
        _sub(usage_records=[{"quantity": 5}]),
        False,
    ),
    "empty_tenant_id": (_sub(tenant_id=""), False),
}

_JSON_FENCE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_schema(text: str) -> Optional[dict]:
    """Last ```json fenced block, else the largest parseable {...} span."""
    blocks = _JSON_FENCE.findall(text)
    candidates = [b.strip() for b in blocks[::-1]]
    if not candidates:
        brace = re.search(r"\{[\s\S]*\}", text)
        if brace:
            candidates = [brace.group(0)]
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def gold_verdict(task_id: str, output_text: str) -> tuple[bool, dict]:
    assert task_id == "billing_schema", task_id
    schema = extract_schema(output_text)
    if schema is None:
        return False, {"reason": "no JSON schema found in output"}
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except jsonschema.exceptions.SchemaError as exc:
        return False, {"reason": f"not a valid draft 2020-12 schema: {exc.message}"}
    failures = []
    for label, (instance, should_accept) in INSTANCES.items():
        accepted = validator.is_valid(instance)
        if accepted != should_accept:
            failures.append(
                f"{label}: {'accepted' if accepted else 'rejected'}, "
                f"expected {'accept' if should_accept else 'reject'}"
            )
    if failures:
        return False, {"reason": "battery mismatch", "failures": failures}
    return True, {"instances": len(INSTANCES)}


def sanity_check() -> None:
    ok, meta = gold_verdict("billing_schema", REFERENCE_OUTPUT)
    assert ok, f"reference schema failed its own battery: {meta}"
    valid = sum(1 for _, is_valid in INSTANCES.values() if is_valid)
    invalid = len(INSTANCES) - valid
    assert valid >= 6 and invalid >= 10, (valid, invalid)


if __name__ == "__main__":
    sanity_check()
    print(f"schema_gold sanity checks passed ({len(INSTANCES)} instances)")
