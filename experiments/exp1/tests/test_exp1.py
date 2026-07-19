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


def test_judge_prompts_render_safely():
    """Regression: judge prompts legally contain literal braces (the schema
    contract text); rendering must be literal substitution, not str.format."""
    from ..gate import render_judge_prompt

    for proxies in proxy_bank.build_proxy_bank().values():
        for p in proxies:
            if p.judge_prompt is None:
                continue
            rendered = render_judge_prompt(p.judge_prompt, "<<OUTPUT>>")
            assert "<<OUTPUT>>" in rendered, p.proxy_id
            assert "{output}" not in rendered, p.proxy_id


def test_sql_gold_extraction_robustness():
    """Regression: semicolons in comments, dialect-tagged fences, and DDL
    echo blocks must not false-reject a correct query."""
    from ..gold import sql_gold

    ref = sql_gold.REFERENCE_QUERIES["sql_ltv_top10"]
    commented = ref.replace("-- Top 10", "-- Top 10; net of refunds --")
    assert sql_gold.gold_verdict(
        "sql_ltv_top10", "```sql\n" + commented + "\n```")[0]
    assert sql_gold.gold_verdict(
        "sql_ltv_top10", "```sqlite\n" + ref + "\n```")[0]
    echoed = ("```sql\n" + ref + "\n```\n\nSchema recap:\n```sql\n"
              + sql_gold.DDL + "\n```")
    assert sql_gold.gold_verdict("sql_ltv_top10", echoed)[0]
    ok, meta = sql_gold.gold_verdict("sql_ltv_top10",
                                     "```sql\nSELECT 1; SELECT 2;\n```")
    assert not ok and "execution error" in meta["reason"]


def test_schema_gold_ignores_trailing_example():
    """Regression: an appended example-instance block must not shadow the
    schema (it would otherwise vacuously accept everything)."""
    import json as json_mod

    from ..gold import schema_gold

    example = json_mod.dumps(
        {"subscription_id": "s", "tenant_id": "t", "status": "active",
         "seats": 1, "plan": {"pricing_model": "seat",
                              "price_per_seat_cents": 0,
                              "included_usage_units": 0}})
    out = (schema_gold.REFERENCE_OUTPUT
           + "\n\nExample record:\n```json\n" + example + "\n```")
    assert schema_gold.gold_verdict("billing_schema", out)[0]


def test_schema_battery_clause_coverage():
    """Regression: relaxing any single pinned clause must fail the battery."""
    import json as json_mod

    from ..gold import schema_gold

    def relaxed(mutate):
        schema = json_mod.loads(json_mod.dumps(schema_gold.REFERENCE_SCHEMA))
        mutate(schema)
        return "```json\n" + json_mod.dumps(schema) + "\n```"

    relaxations = [
        lambda s: s["required"].remove("subscription_id"),
        lambda s: s["required"].remove("status"),
        lambda s: s["required"].remove("seats"),
        lambda s: s["properties"]["subscription_id"].pop("minLength"),
        lambda s: s["properties"]["plan"]["properties"][
            "price_per_seat_cents"].update(type="number"),
        lambda s: s["properties"]["plan"]["properties"][
            "included_usage_units"].pop("minimum"),
        lambda s: s["properties"]["plan"]["required"].remove("pricing_model"),
        lambda s: s["properties"]["plan"]["required"].remove(
            "price_per_seat_cents"),
        lambda s: s["properties"]["usage_records"].pop("type"),
        lambda s: s["properties"]["usage_records"]["items"]["required"].remove(
            "quantity"),
        lambda s: s["properties"]["usage_records"]["items"]["properties"][
            "unit"].pop("minLength"),
    ]
    for i, mutate in enumerate(relaxations):
        ok, _ = schema_gold.gold_verdict("billing_schema", relaxed(mutate))
        assert not ok, f"relaxation #{i} passed the battery — coverage gap"


def test_csv_gold_tolerates_main_blocks_and_prints():
    """Regression: __main__ demo blocks must not run; candidate stdout writes
    and trailing usage-example blocks must not corrupt the verdict."""
    from ..gold import csv_gold

    with_main = (csv_gold.REFERENCE_OUTPUT[:-3]
                 + '\nif __name__ == "__main__":\n'
                 + "    raise SystemExit(1)\n```")
    assert csv_gold.gold_verdict("csv_parser", with_main)[0]
    noisy = csv_gold.REFERENCE_OUTPUT.replace(
        "def parse_csv",
        'import sys\nsys.stdout.write("dbg")\ndef parse_csv', 1)
    assert csv_gold.gold_verdict("csv_parser", noisy)[0]
    with_usage = (csv_gold.REFERENCE_OUTPUT
                  + "\n\nUsage:\n```python\nprint(parse_csv('a,b'))\n```")
    assert csv_gold.gold_verdict("csv_parser", with_usage)[0]


def test_output_id_uniqueness():
    from ..models import Origin as OriginEnum, Output

    dup = [Output(task_id="t", text="same", origin=OriginEnum.SAMPLED),
           Output(task_id="t", text="same", origin=OriginEnum.SAMPLED)]
    population.ensure_unique_ids(dup)
    assert dup[0].output_id != dup[1].output_id


def test_degenerate_metrics_yield_invalid_verdict():
    rows = [
        {"proxy_id": f"p{i}", "task_id": "t", "intended_class": "valid",
         "kind": "executable", "empirical_validity": v,
         "balanced_accuracy": 0.5,
         "gate": {"holistic": {"validity_score": 0.5, "sample_variance": 0.0,
                               "subjudgments": {}}}}
        for i, v in enumerate([0.9, 0.1, 0.7, -0.2])
    ]
    metrics = analyze.compute_metrics(rows, "holistic")
    assert metrics["degenerate"]
    call, reason = analyze.verdict(metrics)
    assert call == "INVALID" and "undefined" in reason


def test_empty_task_selection_fails_fast():
    try:
        run_exp1.main(["--mock", "--tasks", ""])
        raise AssertionError("empty --tasks did not exit")
    except SystemExit as exc:
        assert "no tasks selected" in str(exc)


def test_gate_cache_fingerprint_tracks_code():
    from .. import gate as gate_module

    original = gate_module._HOLISTIC_PROMPT
    fp_before = gate_module._gate_fingerprint()
    try:
        gate_module._HOLISTIC_PROMPT = original + " EDITED"
        fp_after = gate_module._gate_fingerprint()
    finally:
        gate_module._HOLISTIC_PROMPT = original
    assert fp_before != fp_after
    assert gate_module._gate_fingerprint() == fp_before


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
