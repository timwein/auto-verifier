#!/usr/bin/env python3
"""
Guard tests for Experiment 1. Run: python -m experiments.exp1.tests.test_exp1

Covers spec section 9 threats:
  * gold trustworthiness (reference passes; known-wrong mutations fail),
  * population spans the spectrum (both passes and fails per task),
  * leakage guard (gate signature cannot receive gold/population/class),
  * proxy empirical-validity ordering sanity (valid > irrelevant on average).
"""

import copy
import inspect
import json

from .. import gate as G
from .. import population as P
from .. import proxy_bank as B
from ..gold import schema_gold as JG
from ..gold import sql_gold as SG


def test_sql_gold_trustworthy():
    for tid, spec in SG.SQL_TASKS.items():
        assert SG.gold_verdict(tid, SG.reference_output(tid)) == 1.0, f"{tid} ref must pass"
        # include refunds -> wrong
        broken = "```sql\n" + spec.reference_query.replace("WHERE o.status = 'paid' ", "") + ";\n```"
        assert SG.gold_verdict(tid, broken) == 0.0, f"{tid} include-refunds must fail"
    # ranking-specific: ASC must break the ordered task
    q = SG.SQL_TASKS["sql_ltv_top10"].reference_query
    assert SG.gold_verdict("sql_ltv_top10", "```sql\n" + q.replace("DESC", "ASC") + ";\n```") == 0.0
    print("✓ SQL gold trustworthy")


def test_schema_gold_trustworthy():
    for tid, spec in JG.SCHEMA_TASKS.items():
        assert JG.gold_verdict(tid, JG.reference_output(tid)) == 1.0, f"{tid} ref must pass"
        loosened = copy.deepcopy(spec.reference_schema); loosened.pop("required", None)
        assert JG.gold_verdict(tid, "```json\n" + json.dumps(loosened) + "\n```") == 0.0
        loose2 = copy.deepcopy(spec.reference_schema); loose2["additionalProperties"] = True
        assert JG.gold_verdict(tid, "```json\n" + json.dumps(loose2) + "\n```") == 0.0
    print("✓ schema gold trustworthy")


def test_population_spans_spectrum():
    for tid, task in P.all_tasks().items():
        pop = P.build_population(task)
        bal = P.balance(pop)
        assert bal["n_pass"] > 0 and bal["n_fail"] > 0, f"{tid} not balanced: {bal}"
        assert 0.2 <= bal["pass_frac"] <= 0.8, f"{tid} too imbalanced: {bal}"
        # every authored 'expected' label must agree with the executable gold
        for o in pop:
            assert o.gold_meta.get("agrees_with_expected", True), \
                f"{tid}:{o.output_id} expected-vs-gold mismatch"
    print("✓ populations span the spectrum and labels agree with gold")


def test_gate_signature_leakage_guard():
    forbidden = {"gold", "gold_verdict", "verdicts", "population", "outputs",
                 "mutation", "mutations", "intended_class", "empirical_validity"}
    for fn in (G.holistic_gate, G.decomposed_gate):
        params = set(inspect.signature(fn).parameters)
        leaked = params & forbidden
        assert not leaked, f"{fn.__name__} leaks forbidden params: {leaked}"
        # positional inputs must be exactly the two allowed strings
        pos = [p for p, v in inspect.signature(fn).parameters.items()
               if v.kind in (v.POSITIONAL_ONLY, v.POSITIONAL_OR_KEYWORD)]
        assert pos[:2] == ["task_prompt", "proxy_definition"], pos
    print("✓ gate signature leakage guard")


def test_proxy_validity_ordering():
    for tid, task in P.all_tasks().items():
        pop = P.build_population(task)
        by_class = {"valid": [], "confounded": [], "irrelevant": []}
        for proxy in B.build_proxy_bank(task):
            r = B.run_proxy(proxy, pop, mock=True)
            by_class[proxy.intended_class.value].append(r.empirical_validity)
        mean = lambda xs: sum(xs) / len(xs)
        assert mean(by_class["valid"]) > mean(by_class["irrelevant"]), \
            f"{tid}: valid proxies should out-track irrelevant ones"
    print("✓ valid proxies out-track irrelevant (experiment is discriminating)")


def main():
    test_sql_gold_trustworthy()
    test_schema_gold_trustworthy()
    test_population_spans_spectrum()
    test_gate_signature_leakage_guard()
    test_proxy_validity_ordering()
    print("\nALL GUARD TESTS PASSED")


if __name__ == "__main__":
    main()
