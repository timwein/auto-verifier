#!/usr/bin/env python3
from __future__ import annotations
"""
Experiment 1 — Gold-Proxy Separation Harness: data model.

Implements the dataclasses described in the Exp-1 spec section 1.

Note on reuse: the spec asks to reuse enums/types from
``rubric_system/models.py`` where they already exist. They don't — that
module's enums (ScoringMethod, CriterionTier) describe rubric *criteria*,
not the proxy/gold concepts this experiment needs. So the enums below are
defined fresh. This is recorded in DESIGN_NOTES.md.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Callable


# ============================================================================
# Enums
# ============================================================================

class Origin(str, Enum):
    """Where a candidate Output came from."""
    REFERENCE = "reference"   # the known-correct anchor
    SAMPLED = "sampled"       # generated from the model at varied temperature
    MUTATED = "mutated"       # reference with a known deterministic mutation applied


class ProxyKind(str, Enum):
    """How a proxy check is implemented."""
    EXECUTABLE = "executable"   # a Python predicate over the output text
    LLM_JUDGED = "llm_judged"   # a judge prompt asking a model to check the predicate


class IntendedClass(str, Enum):
    """Author's *hypothesis* about a proxy. Used only for stratified analysis,
    NEVER shown to the gate, NEVER used to compute empirical validity."""
    VALID = "valid"             # genuinely tracks correctness
    CONFOUNDED = "confounded"   # correlates on typical outputs, decouples under mutation
    IRRELEVANT = "irrelevant"   # near-zero causal link to correctness


# ============================================================================
# Core dataclasses (spec section 1)
# ============================================================================

@dataclass
class GroundedTask:
    """A task with a deterministic (execute-and-compare) gold verifier."""
    task_id: str
    prompt: str
    reference_output: str
    family: str                      # "sql" | "schema"
    gold_verifier_ref: str           # handle/name of the deterministic check
    fixtures: dict = field(default_factory=dict)  # seeded data, schemas, instances


@dataclass
class Output:
    """One candidate output for a task."""
    task_id: str
    text: str
    origin: Origin
    output_id: str = ""
    gold_verdict: Optional[float] = None      # bool/float in [0,1] from the gold
    gold_meta: dict = field(default_factory=dict)  # e.g. which mutation was applied


@dataclass
class ProxyCheck:
    """A manufactured check claiming to verify 'this output is correct'."""
    proxy_id: str
    task_id: str
    definition: str                  # natural-language spec of what the check asserts
    kind: ProxyKind
    intended_class: IntendedClass    # author label; analysis only, never to the gate
    # impl: executable predicate (text -> bool) OR the judge prompt template (str).
    impl: Any = None


@dataclass
class ProxyResult:
    """Result of running a proxy over the output population."""
    proxy_id: str
    task_id: str
    per_output_verdicts: dict = field(default_factory=dict)  # output_id -> bool
    empirical_validity: Optional[float] = None  # MCC vs gold, in [-1, 1]
    balanced_accuracy: Optional[float] = None
    n_outputs: int = 0


@dataclass
class GateScore:
    """The gate's a-priori judgment of a proxy, blind to the gold."""
    proxy_id: str
    task_id: str
    validity_score: float            # in [0, 1]
    rationale: str = ""
    gate_model: str = ""
    variant: str = ""                # "holistic" | "decomposed"
    subjudgments: dict = field(default_factory=dict)  # decomposed sub-scores
    samples: list = field(default_factory=list)        # per-sample scores (voting@k)
    sample_variance: Optional[float] = None
