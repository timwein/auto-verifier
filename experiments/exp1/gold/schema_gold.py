#!/usr/bin/env python3
from __future__ import annotations
"""
JSON-Schema gold verifier for Experiment 1 — SELF-CONTAINED, BEHAVIORAL TRUTH.

The repo has no JSON-schema validator (jsonschema is never imported). So we build
our own trustworthy ground truth: per task, a pinned *reference schema* plus a set
of held-out instances each labeled valid/invalid. A candidate schema is correct iff
it ACCEPTS every valid instance and REJECTS every invalid one.

`gold_verdict(task_id, candidate_text)` parses the candidate's JSON Schema, validates
each held-out instance against it, and returns 1.0 iff every classification matches.

IMPORTANT: authored independently of proxy_bank.py; shares NO helpers with it.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


# ---------------------------------------------------------------------------
# Task specs: reference schema + held-out labeled instances
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchemaTaskSpec:
    task_id: str
    prompt: str
    reference_schema: dict
    # instances: list of (instance, should_validate)
    instances: tuple = field(default_factory=tuple)


_BILLING_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["tenant_id", "plan", "pricing_model", "amount_cents", "currency"],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "plan": {"type": "string", "enum": ["free", "pro", "enterprise"]},
        "pricing_model": {"type": "string", "enum": ["seat", "usage"]},
        "seats": {"type": "integer", "minimum": 1},
        "usage_unit": {"type": "string"},
        "amount_cents": {"type": "integer", "minimum": 0},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
    },
}

_BILLING_INSTANCES = (
    # valid
    ({"tenant_id": "t_1", "plan": "pro", "pricing_model": "seat", "seats": 5,
      "amount_cents": 5000, "currency": "USD"}, True),
    ({"tenant_id": "t_2", "plan": "free", "pricing_model": "usage",
      "usage_unit": "api_call", "amount_cents": 0, "currency": "EUR"}, True),
    ({"tenant_id": "t_3", "plan": "enterprise", "pricing_model": "seat", "seats": 1,
      "amount_cents": 999999, "currency": "GBP"}, True),
    ({"tenant_id": "t_4", "plan": "pro", "pricing_model": "usage",
      "amount_cents": 1200, "currency": "JPY"}, True),
    # invalid
    ({"plan": "pro", "pricing_model": "seat", "amount_cents": 100,
      "currency": "USD"}, False),                                    # missing tenant_id
    ({"tenant_id": "t_5", "plan": "gold", "pricing_model": "seat",
      "amount_cents": 100, "currency": "USD"}, False),               # bad plan enum
    ({"tenant_id": "t_6", "plan": "pro", "pricing_model": "monthly",
      "amount_cents": 100, "currency": "USD"}, False),               # bad pricing_model
    ({"tenant_id": "t_7", "plan": "pro", "pricing_model": "seat",
      "amount_cents": -5, "currency": "USD"}, False),                # negative amount
    ({"tenant_id": "t_8", "plan": "pro", "pricing_model": "seat",
      "amount_cents": 100, "currency": "usd"}, False),               # bad currency pattern
    ({"tenant_id": "t_9", "plan": "pro", "pricing_model": "seat",
      "amount_cents": "100", "currency": "USD"}, False),             # amount wrong type
    ({"tenant_id": "t_10", "plan": "pro", "pricing_model": "seat", "seats": 0,
      "amount_cents": 100, "currency": "USD"}, False),               # seats below minimum
    ({"tenant_id": "t_11", "plan": "pro", "pricing_model": "seat",
      "amount_cents": 100, "currency": "USD", "extra": 1}, False),   # additionalProperties
)


_EVENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["event_id", "type", "created_at", "data"],
    "properties": {
        "event_id": {"type": "string", "pattern": "^evt_[A-Za-z0-9]+$"},
        "type": {"type": "string",
                 "enum": ["invoice.paid", "invoice.failed", "subscription.updated"]},
        "created_at": {"type": "integer", "minimum": 0},
        "data": {"type": "object"},
        "livemode": {"type": "boolean"},
    },
}

_EVENT_INSTANCES = (
    # valid
    ({"event_id": "evt_abc123", "type": "invoice.paid", "created_at": 1700000000,
      "data": {"amount": 100}}, True),
    ({"event_id": "evt_X9", "type": "subscription.updated", "created_at": 0,
      "data": {}, "livemode": True}, True),
    ({"event_id": "evt_z", "type": "invoice.failed", "created_at": 12,
      "data": {"reason": "card_declined"}}, True),
    # invalid
    ({"type": "invoice.paid", "created_at": 1, "data": {}}, False),          # missing event_id
    ({"event_id": "abc123", "type": "invoice.paid", "created_at": 1,
      "data": {}}, False),                                                   # bad id pattern
    ({"event_id": "evt_1", "type": "refund.created", "created_at": 1,
      "data": {}}, False),                                                   # bad type enum
    ({"event_id": "evt_1", "type": "invoice.paid", "created_at": -1,
      "data": {}}, False),                                                   # created_at < 0
    ({"event_id": "evt_1", "type": "invoice.paid", "created_at": 1,
      "data": []}, False),                                                   # data wrong type
    ({"event_id": "evt_1", "type": "invoice.paid", "created_at": 1,
      "data": {}, "livemode": "yes"}, False),                                # livemode wrong type
    ({"event_id": "evt_1", "type": "invoice.paid", "created_at": 1,
      "data": {}, "extra": 1}, False),                                       # additionalProperties
)


SCHEMA_TASKS = {
    "billing_schema": SchemaTaskSpec(
        task_id="billing_schema",
        prompt=(
            "Design a JSON Schema (draft 2020-12) for a multi-tenant SaaS billing "
            "record supporting both seat-based and usage-based pricing. Required "
            "fields: tenant_id (non-empty string), plan (one of free/pro/enterprise), "
            "pricing_model (one of seat/usage), amount_cents (non-negative integer), "
            "currency (3-letter uppercase ISO code). Optional: seats (integer >= 1), "
            "usage_unit (string). Reject unknown fields."
        ),
        reference_schema=_BILLING_SCHEMA,
        instances=_BILLING_INSTANCES,
    ),
    "event_schema": SchemaTaskSpec(
        task_id="event_schema",
        prompt=(
            "Design a JSON Schema (draft 2020-12) for a webhook event envelope. "
            "Required fields: event_id (string matching ^evt_[A-Za-z0-9]+$), type "
            "(one of invoice.paid/invoice.failed/subscription.updated), created_at "
            "(non-negative integer unix timestamp), data (object). Optional: livemode "
            "(boolean). Reject unknown fields."
        ),
        reference_schema=_EVENT_SCHEMA,
        instances=_EVENT_INSTANCES,
    ),
}


# ---------------------------------------------------------------------------
# Parsing + validation
# ---------------------------------------------------------------------------

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.+?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_schema(text: str) -> Optional[dict]:
    """Parse a JSON Schema object out of a candidate output (fenced or raw)."""
    m = _JSON_BLOCK.search(text)
    candidate = m.group(1) if m else text.strip()
    # If raw, try to locate the outermost {...}.
    if not m:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = candidate[start:end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _accepts(validator: Draft202012Validator, instance) -> bool:
    return validator.is_valid(instance)


def gold_verdict(task_id: str, candidate_text: str) -> float:
    """1.0 iff candidate schema classifies EVERY held-out instance correctly."""
    spec = SCHEMA_TASKS[task_id]
    schema = extract_schema(candidate_text)
    if schema is None:
        return 0.0
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except (SchemaError, Exception):
        return 0.0
    for instance, should_validate in spec.instances:
        if _accepts(validator, instance) != should_validate:
            return 0.0
    return 1.0


def reference_output(task_id: str) -> str:
    """The known-correct candidate text (reference anchor)."""
    spec = SCHEMA_TASKS[task_id]
    return "```json\n" + json.dumps(spec.reference_schema, indent=2) + "\n```"
