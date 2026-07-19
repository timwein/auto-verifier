"""Exp-1 data model (SPEC.md section 1).

Defined fresh rather than imported: rubric_system/models.py was inventoried
(see DESIGN_NOTES.md) and contains no counterpart for any of these — its enums
classify rubric-criteria scoring math, not proxy/gold concepts. Two repo
conventions are adopted: the sha256(task)[:8] task-hash key and call-site
asdict() serialization (with explicit Enum -> value conversion, which the
repo's bare asdict convention lacks).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class Origin(str, Enum):
    REFERENCE = "reference"
    SAMPLED = "sampled"
    MUTATED = "mutated"


class ProxyKind(str, Enum):
    EXECUTABLE = "executable"
    LLM_JUDGED = "llm_judged"


class IntendedClass(str, Enum):
    """Author's hypothesis about a proxy. Stratified analysis only — never
    shown to the gate, never used to compute empirical_validity."""

    VALID = "valid"
    CONFOUNDED = "confounded"
    IRRELEVANT = "irrelevant"


def task_hash(task_prompt: str) -> str:
    """Repo convention (ReferencePair.task_hash / ScoredRubricRecord.task_hash)."""
    return hashlib.sha256(task_prompt.strip().encode("utf-8")).hexdigest()[:8]


@dataclass
class GroundedTask:
    task_id: str
    prompt: str
    reference_output: str
    # Handle naming the deterministic check; resolved by gold/__init__.gold_verdict.
    gold_verifier_ref: str

    @property
    def hash(self) -> str:
        return task_hash(self.prompt)


@dataclass
class Output:
    task_id: str
    text: str
    origin: Origin
    gold_verdict: Optional[bool] = None
    gold_meta: dict = field(default_factory=dict)
    output_id: str = ""

    def __post_init__(self) -> None:
        if not self.output_id:
            digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:10]
            self.output_id = f"{self.task_id}:{self.origin.value}:{digest}"


@dataclass
class ProxyCheck:
    proxy_id: str
    task_id: str
    definition: str  # natural-language spec of what the check asserts (gate input)
    kind: ProxyKind
    intended_class: IntendedClass
    # EXECUTABLE: impl is a predicate text -> bool.
    # LLM_JUDGED: impl is None; judge_prompt is sent to the model per output, and
    # mock_predicate is the deterministic offline stand-in.
    impl: Optional[Callable[[str], bool]] = None
    judge_prompt: Optional[str] = None
    mock_predicate: Optional[Callable[[str], bool]] = None


@dataclass
class ProxyResult:
    proxy_id: str
    per_output_verdicts: dict[str, bool]  # output_id -> proxy verdict
    empirical_validity: float  # MCC vs gold across the population (section 4)
    balanced_accuracy: float
    n_outputs: int


@dataclass
class GateScore:
    proxy_id: str
    validity_score: float  # in [0, 1]
    rationale: str
    gate_model: str
    variant: str = "holistic"  # holistic | decomposed
    subjudgments: dict = field(default_factory=dict)  # decomposed sub-scores
    per_sample_scores: list = field(default_factory=list)  # voting@k raw samples
    sample_variance: float = 0.0


def to_jsonable(obj: Any) -> Any:
    """asdict-style serialization that converts Enums to their values and drops
    callables (proxy impls are code, not data)."""
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items() if not callable(v)}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if callable(obj):
        return None
    return obj
