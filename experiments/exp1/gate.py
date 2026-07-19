"""The construct-validity gate under test (SPEC.md section 5).

Hard integrity constraint, enforced by signature: the gate receives ONLY
(task_prompt, proxy_definition) as content. It cannot receive the output
population, gold verdicts, mutations, or the author's intended_class —
tests/test_exp1.py asserts the signature stays that way.

Two variants (spec Bet C): holistic (one score) and decomposed (causal
coupling / externality / contradiction sub-judgments, aggregated by mean).
voting@k (default 3): k samples, median score, per-sample variance recorded.

Model plumbing copies the repo idioms rather than importing them (the repo has
no importable client helper — see DESIGN_NOTES.md): Anthropic client with
httpx timeout (rubric_harness.py:81), repo-default Sonnet model, API-key
fallback env -> .env -> ~/.anthropic/api_key (rubric_harness.py:100-111),
fence->loads->brace JSON extraction (rubric_harness.py:7313-7325).

Offline mode (--mock): deterministic scores derived only from the two allowed
inputs via a fixed keyword heuristic plus content-hash jitter. Validates the
pipeline; a mock run is never an experimental verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from pathlib import Path
from typing import Optional

from .models import GateScore

DEFAULT_MODEL = "claude-sonnet-4-20250514"  # repo-wide default (DESIGN_NOTES.md)
_VOTE_TEMPERATURE = 0.7  # non-zero so voting@k is non-degenerate

_HOLISTIC_PROMPT = """You are a construct-validity gate. A proposed CHECK claims to verify that an
output correctly solves a TASK. Your job: estimate, a priori, how valid the
check is as a proxy for true correctness — without seeing any outputs.

A check is VALID to the degree that: an incorrect output passing the check is
practically impossible, and "check fails" strongly implies "output is wrong".
A check is CONFOUNDED if plausible incorrect outputs pass it (it tracks
surface features that correlate with, but do not cause, correctness). A check
is IRRELEVANT if it has near-zero causal link to correctness.

TASK:
{task_prompt}

PROPOSED CHECK:
{proxy_definition}

Think about concrete incorrect outputs that would pass this check, and correct
outputs that would fail it. Then answer with ONLY a JSON object:
{{"validity_score": <float 0.0-1.0>, "rationale": "<2-4 sentences>"}}"""

_DECOMPOSED_PROMPT = """You are a construct-validity gate. A proposed CHECK claims to verify that an
output correctly solves a TASK. Score three separate sub-judgments about the
check, a priori, without seeing any outputs. Each is a float in [0, 1].

1. causal_coupling — Under what conditions does the check PASS while the
   output is actually WRONG? Enumerate concrete confounders. 1.0 = passing
   the check practically guarantees correctness; 0.0 = wrong outputs pass
   easily.
2. externality — Does the check appeal to evidence outside the output's own
   surface form (execution against data, independent held-out instances,
   comparison to an independent reference), or only to the output's own
   text/structure/claims? 1.0 = fully external evidence; 0.0 = pure surface.
3. contradiction — Does "check fails" logically ENTAIL "output is wrong", or
   only correlate with it? 1.0 = failure entails wrongness; 0.0 = failure is
   compatible with a fully correct output.

TASK:
{task_prompt}

PROPOSED CHECK:
{proxy_definition}

Answer with ONLY a JSON object:
{{"causal_coupling": <float>, "externality": <float>, "contradiction": <float>,
  "rationale": "<2-4 sentences>"}}"""

_SUBJUDGMENTS = ("causal_coupling", "externality", "contradiction")


# ---------------------------------------------------------------------------
# Repo-idiom plumbing (copied, not imported — see module docstring).
# ---------------------------------------------------------------------------


def load_api_key() -> Optional[str]:
    """Mirrors rubric_harness.py:100-111: env -> <exp dir>/.env -> ~/.anthropic/api_key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for path in (Path(__file__).parent / ".env", Path.home() / ".anthropic" / "api_key"):
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if "=" in raw:
                raw = raw.split("=", 1)[1].strip().strip("'\"")
            if raw:
                os.environ["ANTHROPIC_API_KEY"] = raw
                return raw
    return None


def make_client():
    import anthropic
    import httpx

    if not load_api_key():
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set (env, experiments/exp1/.env, or "
            "~/.anthropic/api_key). Use --mock for the offline pipeline."
        )
    return anthropic.Anthropic(timeout=httpx.Timeout(600.0, connect=30.0))


def _extract_json(text: str) -> dict:
    """Fence -> raw -> brace-regex, mirroring rubric_harness._extract_json."""
    fence = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    candidates = [fence.group(1)] if fence else []
    candidates.append(text)
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        candidates.append(brace.group(0))
    for cand in candidates:
        try:
            parsed = json.loads(cand.strip())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}


def _call_model(client, model: str, prompt: str, temperature: float) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Mock gate (offline): deterministic in the two allowed inputs only.
# ---------------------------------------------------------------------------

_STRONG_SIGNALS = (
    "exactly equals", "equals the result", "result table exactly",
    "accepts every valid instance and rejects", "matches the contract",
    "expected output", "known-correct", "reference query", "full pinned contract",
)
_EXECUTION_SIGNALS = ("execute", "run the", "run parse_csv", "validate an", "runs without")
_SURFACE_SIGNALS = ("text contains", "mentions", "contains the string",
                    "contains a", "contains an", "includes tenant_id",
                    "references the", "carries a", "calls .strip")
_IRRELEVANT_SIGNALS = ("lines long", "lines.", "uppercase", "well-formatted",
                       "readable", "docstring", "comments", "annotation",
                       "nests at least", "type hints", "professionally",
                       "clean and", "common table expression")


def _hash_unit(*parts: str) -> float:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _mock_component(task_prompt: str, proxy_definition: str, salt: str) -> float:
    d = proxy_definition.lower()
    score = 0.45
    if any(s in d for s in _STRONG_SIGNALS):
        score += 0.38
    if any(s in d for s in _EXECUTION_SIGNALS):
        score += 0.12
    if any(s in d for s in _SURFACE_SIGNALS):
        score -= 0.18
    if any(s in d for s in _IRRELEVANT_SIGNALS):
        score -= 0.30
    score += _hash_unit(task_prompt, proxy_definition, salt) * 0.08 - 0.04
    return max(0.02, min(0.98, score))


# ---------------------------------------------------------------------------
# The gate. Signature is the leakage guard — do not add content parameters.
# ---------------------------------------------------------------------------


def gate_score(
    task_prompt: str,
    proxy_definition: str,
    *,
    variant: str = "holistic",
    model: str = DEFAULT_MODEL,
    votes: int = 3,
    cache_dir: Optional[Path] = None,
    mock: bool = False,
    client=None,
) -> GateScore:
    assert variant in ("holistic", "decomposed"), variant
    cache_key = None
    if cache_dir is not None:
        cache_key = hashlib.sha256(
            json.dumps(
                {"v": variant, "m": model if not mock else "mock", "k": votes,
                 "task": task_prompt, "proxy": proxy_definition, "mock": mock},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        cached = _cache_get(cache_dir, cache_key)
        if cached is not None:
            return cached

    samples: list[dict] = []
    for vote in range(votes):
        if mock:
            samples.append(_mock_sample(task_prompt, proxy_definition, variant, vote))
        else:
            samples.append(
                _model_sample(task_prompt, proxy_definition, variant, model,
                              client, votes)
            )

    scores = [s["validity_score"] for s in samples]
    median = statistics.median(scores)
    variance = statistics.pvariance(scores) if len(scores) > 1 else 0.0
    subjudgments: dict = {}
    if variant == "decomposed":
        subjudgments = {
            key: statistics.median([s["subjudgments"][key] for s in samples])
            for key in _SUBJUDGMENTS
        }
    result = GateScore(
        proxy_id="",  # caller attaches; the gate itself never needs identity
        validity_score=median,
        rationale=samples[0]["rationale"],
        gate_model="mock" if mock else model,
        variant=variant,
        subjudgments=subjudgments,
        per_sample_scores=scores,
        sample_variance=variance,
    )
    if cache_dir is not None and cache_key is not None:
        _cache_put(cache_dir, cache_key, result)
    return result


def _mock_sample(task_prompt: str, proxy_definition: str, variant: str,
                 vote: int) -> dict:
    if variant == "holistic":
        return {
            "validity_score": _mock_component(task_prompt, proxy_definition,
                                              f"holistic:{vote}"),
            "rationale": "mock gate: deterministic keyword heuristic over the "
                         "proxy definition (offline pipeline validation only)",
        }
    subs = {
        key: _mock_component(task_prompt, proxy_definition, f"{key}:{vote}")
        for key in _SUBJUDGMENTS
    }
    return {
        "validity_score": sum(subs.values()) / len(subs),
        "subjudgments": subs,
        "rationale": "mock gate (decomposed): deterministic keyword heuristic "
                     "per sub-judgment (offline pipeline validation only)",
    }


def _model_sample(task_prompt: str, proxy_definition: str, variant: str,
                  model: str, client, votes: int) -> dict:
    if client is None:
        raise RuntimeError("client required for non-mock gate runs")
    template = _HOLISTIC_PROMPT if variant == "holistic" else _DECOMPOSED_PROMPT
    prompt = template.format(task_prompt=task_prompt,
                             proxy_definition=proxy_definition)
    temperature = _VOTE_TEMPERATURE if votes > 1 else 0.0
    text = _call_model(client, model, prompt, temperature)
    parsed = _extract_json(text)
    if variant == "holistic":
        score = _clamp01(parsed.get("validity_score"))
        return {"validity_score": score,
                "rationale": str(parsed.get("rationale", text))[:2000]}
    subs = {key: _clamp01(parsed.get(key)) for key in _SUBJUDGMENTS}
    return {
        "validity_score": sum(subs.values()) / len(subs),
        "subjudgments": subs,
        "rationale": str(parsed.get("rationale", text))[:2000],
    }


def _clamp01(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5  # unparseable judge output -> uninformative midpoint


# ---------------------------------------------------------------------------
# Cache (spec section 10: content-hash keyed, re-runs free).
# ---------------------------------------------------------------------------


def _cache_get(cache_dir: Path, key: str) -> Optional[GateScore]:
    path = Path(cache_dir) / f"{key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return GateScore(**data)


def _cache_put(cache_dir: Path, key: str, score: GateScore) -> None:
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "proxy_id": score.proxy_id,
        "validity_score": score.validity_score,
        "rationale": score.rationale,
        "gate_model": score.gate_model,
        "variant": score.variant,
        "subjudgments": score.subjudgments,
        "per_sample_scores": score.per_sample_scores,
        "sample_variance": score.sample_variance,
    }
    (path / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Judge factory for llm_judged proxies (keyed runs). Not part of the gate:
# this sees outputs by design (it IS the proxy), and is wired by run_exp1.
# ---------------------------------------------------------------------------


def make_proxy_judge(client, model: str = DEFAULT_MODEL):
    def judge(judge_prompt: str, output_text: str) -> bool:
        text = _call_model(
            client, model, judge_prompt.format(output=output_text), 0.0
        )
        return bool(re.search(r"\bPASS\b", text)) and not re.search(r"\bFAIL\b", text)

    return judge


if __name__ == "__main__":
    demo = gate_score(
        "Write a SQL query returning the top 10 customers by lifetime value.",
        "Execute the query against an independently seeded database and assert "
        "its result table exactly equals a known-correct reference query's.",
        variant="decomposed",
        mock=True,
    )
    print(json.dumps(
        {"score": demo.validity_score, "subs": demo.subjudgments,
         "variance": demo.sample_variance}, indent=2))
