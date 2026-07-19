"""Guard + unit tests for Experiment 1 (SPEC.md sections 8-9).

The load-bearing ones:
- test_gate_signature_leakage_guard: the gate cannot receive gold, outputs,
  mutations, or intended_class — enforced by signature, not discipline.
- test_gold_* / test_mutation_hypotheses: the gold is trustworthy (reference
  passes; every breaking mutation fails; every surface mutation passes).
- test_proxy_bank_never_imports_gold: gold/proxy authoring independence.
- test_population_balance: metrics are computed on a non-degenerate population.

Run: python -m experiments.exp1.tests.test_exp1   (or pytest)
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import analyze, gold, population, proxy_bank, run_exp1
from ..gate import gate_score
from ..models import IntendedClass, Origin, ProxyKind

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_gate_signature_leakage_guard():
    sig = inspect.signature(gate_score)
    params = sig.parameters
    positional = [
        n for n, p in params.items()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    assert positional == ["task_prompt", "proxy_definition"], positional
    keyword_only = {n for n, p in params.items() if p.kind == p.KEYWORD_ONLY}
    assert keyword_only == {"variant", "model", "votes", "cache_dir", "mock",
                            "client"}, keyword_only
    forbidden = {"output", "outputs", "population", "gold", "gold_verdict",
                 "verdicts", "mutation", "mutations", "intended_class", "proxy",
                 "proxy_check"}
    leaked = {
        n for n in params
        if n not in ("task_prompt", "proxy_definition")
        and any(f in n.lower() for f in forbidden)
    }
    assert not leaked, f"gate signature leaks experiment state: {leaked}"
    # No *args/**kwargs escape hatch either.
    assert not any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                   for p in params.values())


def test_gold_sanity_and_references_pass():
    gold.sanity_check_all()


def test_mutation_hypotheses_hold():
    """Every breaking mutation fails gold; every preserving mutation passes."""
    for task in gold.build_tasks().values():
        for output in population.build_population(task, include_sampled=False):
            expected = output.gold_meta.get("expected")
            if expected == "break":
                assert output.gold_verdict is False, (
                    f"{task.task_id}/{output.gold_meta['mutation']}: expected "
                    f"break but gold passed")
            elif expected == "preserve":
                assert output.gold_verdict is True, (
                    f"{task.task_id}/{output.gold_meta['mutation']}: expected "
                    f"preserve but gold failed: {output.gold_meta.get('gold_result')}")


def test_population_balance():
    for task in gold.build_tasks().values():
        outputs = population.build_population(task)
        report = population.check_balance(task.task_id, outputs)
        assert 0.25 <= report["pass_rate"] <= 0.75, (task.task_id, report)
        assert report["n"] >= 12, (task.task_id, report)


def test_population_has_all_origins():
    for task in gold.build_tasks().values():
        origins = {o.origin for o in population.build_population(task)}
        assert origins == {Origin.REFERENCE, Origin.SAMPLED, Origin.MUTATED}


def test_proxy_bank_never_imports_gold():
    """Importing proxy_bank must not pull in any gold module (independence)."""
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import experiments.exp1.proxy_bank; "
        "bad = [m for m in sys.modules if 'exp1.gold' in m]; "
        "assert not bad, bad; print('clean')"
    ) % str(REPO_ROOT)
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and "clean" in proc.stdout, proc.stderr


def test_proxy_bank_shape():
    bank = proxy_bank.build_proxy_bank()
    assert set(bank) == set(gold.build_tasks())
    for task_id, proxies in bank.items():
        assert 8 <= len(proxies) <= 12, (task_id, len(proxies))
        classes = {p.intended_class for p in proxies}
        assert classes == {IntendedClass.VALID, IntendedClass.CONFOUNDED,
                           IntendedClass.IRRELEVANT}, task_id
        kinds = {p.kind for p in proxies}
        assert kinds == {ProxyKind.EXECUTABLE, ProxyKind.LLM_JUDGED}, task_id
        for p in proxies:
            if p.kind == ProxyKind.EXECUTABLE:
                assert p.impl is not None, p.proxy_id
            else:
                assert p.judge_prompt and "{output}" in p.judge_prompt, p.proxy_id
                assert p.mock_predicate is not None, p.proxy_id


def test_valid_proxies_track_gold():
    """The flagship valid proxies must reach high MCC via their own substrate."""
    bank = proxy_bank.build_proxy_bank()
    tasks = gold.build_tasks()
    for task_id, flagship in [("sql_ltv_top10", "exec_matches_ref"),
                              ("sql_revenue_by_tier", "exec_matches_ref")]:
        pop = population.build_population(tasks[task_id])
        proxy = next(p for p in bank[task_id]
                     if p.proxy_id == f"{task_id}::{flagship}")
        result = proxy_bank.run_proxy(proxy, pop)
        assert result.empirical_validity >= 0.9, (task_id, result.empirical_validity)


def test_mcc_and_balanced_accuracy():
    assert proxy_bank.mcc([True, True, False, False],
                          [True, True, False, False]) == 1.0
    assert proxy_bank.mcc([False, False, True, True],
                          [True, True, False, False]) == -1.0
    assert proxy_bank.mcc([True, True, True, True],
                          [True, True, False, False]) == 0.0  # degenerate
    assert proxy_bank.balanced_accuracy([True, True, False, False],
                                        [True, True, False, False]) == 1.0
    assert proxy_bank.balanced_accuracy([True, True, True, True],
                                        [True, True, False, False]) == 0.5


def test_auroc_and_spearman():
    assert analyze.auroc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert analyze.auroc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0
    assert analyze.auroc([0.5, 0.5, 0.5, 0.5], [True, True, False, False]) == 0.5
    assert abs(analyze.spearman_rho([1, 2, 3, 4], [1, 2, 3, 4]) - 1.0) < 1e-9
    assert abs(analyze.spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-9


def test_mock_gate_deterministic_and_ordered():
    strong = "Execute the query and assert its result table exactly equals the known-correct reference query result."
    weak = "Assert the query is under 20 lines long."
    s1 = gate_score("task", strong, mock=True)
    s2 = gate_score("task", strong, mock=True)
    w = gate_score("task", weak, mock=True)
    assert s1.validity_score == s2.validity_score
    assert s1.validity_score > w.validity_score
    d = gate_score("task", strong, variant="decomposed", mock=True)
    assert set(d.subjudgments) == {"causal_coupling", "externality",
                                   "contradiction"}
    assert len(d.per_sample_scores) == 3


def test_gate_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        a = gate_score("t", "some proxy definition", mock=True, cache_dir=cache)
        files = list(cache.glob("*.json"))
        assert len(files) == 1
        b = gate_score("t", "some proxy definition", mock=True, cache_dir=cache)
        assert a.validity_score == b.validity_score
        assert a.variant == b.variant


def test_smoke_pipeline_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        code = run_exp1.main(["--smoke", "--mock", "--out", tmp])
        assert code == 0
        assert (Path(tmp) / "exp1_raw.json").exists()


def test_verdict_rule():
    green = {"spearman_rho": 0.7, "rho_ci": [0.4, 0.9],
             "auroc": 0.9, "auroc_ci": [0.75, 1.0]}
    assert analyze.verdict(green)[0] == "GREENLIGHT"
    kill = {"spearman_rho": 0.1, "rho_ci": [-0.2, 0.4],
            "auroc": 0.9, "auroc_ci": [0.75, 1.0]}
    assert analyze.verdict(kill)[0] == "KILL"
    wide_ci = {"spearman_rho": 0.7, "rho_ci": [0.1, 0.9],
               "auroc": 0.9, "auroc_ci": [0.75, 1.0]}
    assert analyze.verdict(wide_ci)[0] == "AMBIGUOUS"


ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failures = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    raise SystemExit(1 if failures else 0)
