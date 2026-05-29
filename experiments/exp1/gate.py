#!/usr/bin/env python3
from __future__ import annotations
"""
The construct-validity GATE under test (spec section 5).

Given ONLY (task_prompt, proxy_definition), the gate outputs a validity_score in
[0,1] + rationale. It must predict, a priori and blind, whether "the check fails"
implies "the output is wrong".

HARD INTEGRITY CONSTRAINT (enforced by signature): the gate functions accept only
`task_prompt: str` and `proxy_definition: str`. They CANNOT receive the output
population, per-output verdicts, the gold verifier, the mutations, or the author's
intended_class. Passing those is impossible without changing the signature.

Two variants:
  * holistic   — one prompt, one score.
  * decomposed — three sub-judgments (causal coupling / externality / contradiction),
                 aggregated by mean and min (both recorded).

voting@3: each judgment is sampled 3x; we take the median and record per-sample
variance (judges destabilize on close cases — we want to see that).

Client plumbing reuses the repo's pattern: anthropic.Anthropic(timeout=...) with the
ANTHROPIC_API_KEY / .env / ~/.anthropic/api_key fallback (cf. rubric_harness.py).
A --mock mode returns deterministic pseudo-scores derived ONLY from the two allowed
strings, so the whole pipeline runs offline without leaking the class label.
"""

import hashlib
import json
import os
import re
import statistics
from pathlib import Path
from typing import Optional

from .models import GateScore

DEFAULT_MODEL = "claude-sonnet-4-20250514"
VOTES = 3


# ---------------------------------------------------------------------------
# Client plumbing (reused pattern)
# ---------------------------------------------------------------------------

def load_api_key() -> Optional[str]:
    """Mirror rubric_harness.py:103-110 — env, then .env / ~/.anthropic/api_key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for p in [Path(__file__).resolve().parent / ".env",
              Path(__file__).resolve().parents[2] / ".env",
              Path.home() / ".anthropic" / "api_key"]:
        try:
            if p.exists():
                text = p.read_text().strip()
                key = text.split("=", 1)[1].strip().strip('"') if "=" in text else text
                if key:
                    os.environ["ANTHROPIC_API_KEY"] = key
                    return key
        except Exception:
            pass
    return None


def make_client():
    import anthropic  # imported lazily so --mock runs without the package installed
    import httpx
    return anthropic.Anthropic(timeout=httpx.Timeout(600.0, connect=30.0))


def _call_model(client, prompt: str, model: str, temperature: float) -> str:
    resp = client.messages.create(
        model=model, max_tokens=600, temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_HOLISTIC = """You are auditing whether a verification CHECK is a valid proxy for a CLAIM.

CLAIM (the task an output is supposed to satisfy):
{task}

CHECK (a proposed way to verify the output is correct):
{check}

Question: if this CHECK fails, does that reliably imply the output is WRONG — and if
the CHECK passes, does that reliably imply the output is CORRECT? A valid check is
causally coupled to correctness. An invalid check can pass while the output is wrong
(it keys on surface features), or has little to do with correctness at all.

You do NOT see any outputs or results — judge a priori from the claim and check alone.

Respond with ONLY a JSON object:
{{"score": <float 0..1, how valid a proxy this check is>, "rationale": "<one sentence>"}}"""

_SUBJUDGMENTS = {
    "causal_coupling": (
        "Sub-judgment — CAUSAL COUPLING. Under what conditions could this CHECK PASS while "
        "the output is actually WRONG? If there are many such conditions (the check keys on "
        "surface/structural features that wrong outputs can also have), score LOW. If a passing "
        "check essentially forces correctness, score HIGH."),
    "externality": (
        "Sub-judgment — EXTERNALITY. Does the CHECK appeal only to the artifact's own self-"
        "assertions / surface form, or does it test behavior against something external and "
        "independent (execution, a held-out battery, ground truth)? Self-referential surface "
        "checks score LOW; checks grounded in external behavior score HIGH."),
    "contradiction": (
        "Sub-judgment — CONTRADICTION. Does 'the CHECK fails' LOGICALLY ENTAIL 'the output is "
        "wrong', or does it merely CORRELATE? Entailment scores HIGH; loose correlation scores LOW."),
}

_DECOMP = """You are auditing whether a verification CHECK is a valid proxy for a CLAIM.

CLAIM:
{task}

CHECK:
{check}

{subjudgment}

You do NOT see any outputs or results — judge a priori from the claim and check alone.
Respond with ONLY a JSON object:
{{"score": <float 0..1>, "rationale": "<one sentence>"}}"""


# ---------------------------------------------------------------------------
# Mock scoring (deterministic; uses ONLY the two allowed strings)
# ---------------------------------------------------------------------------

_VALID_CUES = ["execute", "result set equals", "reference", "enforce", "reject",
               "classified correctly", "ground truth", "battery", "behavior"]
_SURFACE_CUES = ["contains", "mention", "lists", "declares", "looks like", "plausible",
                 "presence", "expected clauses", "property names", "expected fields"]
_STYLE_CUES = ["concise", "readable", "comment", "pretty", "style", "lines", "$schema",
               "indented", "well-formatted", "formatted"]


def _mock_base_score(task: str, check: str) -> float:
    c = check.lower()
    score = 0.5
    score += 0.18 * sum(c.count(w) > 0 for w in _VALID_CUES)
    score -= 0.10 * sum(c.count(w) > 0 for w in _SURFACE_CUES)
    score -= 0.16 * sum(c.count(w) > 0 for w in _STYLE_CUES)
    return max(0.02, min(0.98, score))


def _mock_jitter(task: str, check: str, salt: str) -> float:
    h = hashlib.sha256(f"{salt}|{task}|{check}".encode()).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF - 0.5) * 0.08  # +-0.04


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse(text: str) -> tuple[float, str]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return max(0.0, min(1.0, float(obj.get("score", 0.5)))), str(obj.get("rationale", ""))
        except Exception:
            pass
    m = re.search(r"(\d*\.?\d+)", text)
    return (max(0.0, min(1.0, float(m.group(1)))) if m else 0.5), text[:160]


# ---------------------------------------------------------------------------
# Gate variants
# ---------------------------------------------------------------------------

def _vote(sampler, k: int = VOTES) -> tuple[float, list, float, str]:
    """Run sampler k times -> (median, samples, variance, last_rationale)."""
    samples, rationale = [], ""
    for i in range(k):
        s, r = sampler(i)
        samples.append(s)
        rationale = r or rationale
    median = float(statistics.median(samples))
    var = float(statistics.pvariance(samples)) if len(samples) > 1 else 0.0
    return median, samples, var, rationale


def holistic_gate(task_prompt: str, proxy_definition: str, *, proxy_id: str = "",
                  task_id: str = "", client=None, model: str = DEFAULT_MODEL,
                  mock: bool = True, k: int = VOTES) -> GateScore:
    def sample(i: int):
        if mock or client is None:
            return (max(0.0, min(1.0, _mock_base_score(task_prompt, proxy_definition)
                                 + _mock_jitter(task_prompt, proxy_definition, f"h{i}"))),
                    "mock")
        text = _call_model(client, _HOLISTIC.format(task=task_prompt, check=proxy_definition),
                           model, temperature=0.7)
        return _parse(text)

    median, samples, var, rationale = _vote(sample, k)
    return GateScore(proxy_id=proxy_id, task_id=task_id, validity_score=median,
                     rationale=rationale, gate_model="mock" if (mock or client is None) else model,
                     variant="holistic", samples=samples, sample_variance=var)


def decomposed_gate(task_prompt: str, proxy_definition: str, *, proxy_id: str = "",
                    task_id: str = "", client=None, model: str = DEFAULT_MODEL,
                    mock: bool = True, k: int = VOTES) -> GateScore:
    subjudgments = {}
    all_samples = []
    for name, instruction in _SUBJUDGMENTS.items():
        def sample(i: int, instruction=instruction, name=name):
            if mock or client is None:
                base = _mock_base_score(task_prompt, proxy_definition)
                # nudge each sub-axis a little so they're not identical
                axis = {"causal_coupling": 0.0, "externality": -0.05, "contradiction": 0.05}[name]
                return (max(0.0, min(1.0, base + axis
                                     + _mock_jitter(task_prompt, proxy_definition, f"{name}{i}"))),
                        "mock")
            prompt = _DECOMP.format(task=task_prompt, check=proxy_definition, subjudgment=instruction)
            return _parse(_call_model(client, prompt, model, temperature=0.7))

        median, samples, var, _ = _vote(sample, k)
        subjudgments[name] = {"score": median, "samples": samples, "variance": var}
        all_samples.extend(samples)

    scores = [v["score"] for v in subjudgments.values()]
    agg_mean = float(sum(scores) / len(scores))
    agg_min = float(min(scores))
    subjudgments["_aggregate_mean"] = agg_mean
    subjudgments["_aggregate_min"] = agg_min
    return GateScore(proxy_id=proxy_id, task_id=task_id, validity_score=agg_mean,
                     rationale=f"decomposed mean={agg_mean:.2f} min={agg_min:.2f}",
                     gate_model="mock" if (mock or client is None) else model,
                     variant="decomposed", subjudgments=subjudgments, samples=all_samples,
                     sample_variance=float(statistics.pvariance(all_samples)) if len(all_samples) > 1 else 0.0)
