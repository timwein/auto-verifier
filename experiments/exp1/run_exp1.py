"""Experiment 1 orchestrator (SPEC.md sections 7-8).

Build order: tasks -> populations (gold-labeled, balance-enforced) -> frozen
proxy bank -> proxy results -> gate scores (holistic/decomposed, voting@k)
-> metrics -> results/exp1_raw.json + REPORT.md + calibration PNGs.

Usage:
    python -m experiments.exp1.run_exp1 --smoke --mock   # tiny end-to-end check
    python -m experiments.exp1.run_exp1 --mock           # full offline pipeline
    python -m experiments.exp1.run_exp1 --tasks all --gate both   # real (keyed)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import analyze, gate as gate_mod, gold, population, proxy_bank
from .models import Origin, to_jsonable

RESULTS_DIR = Path(__file__).parent / "results"

SMOKE_TASK = "sql_ltv_top10"
SMOKE_PROXIES = ("exec_matches_ref", "text_under_20_lines")
SMOKE_MUTATIONS = ("asc_order", "ignores_refunds_sign")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Experiment 1")
    parser.add_argument("--tasks", default="all",
                        help="comma-separated task ids, or 'all'")
    parser.add_argument("--gate", default="both",
                        choices=["holistic", "decomposed", "both"])
    parser.add_argument("--votes", type=int, default=3)
    parser.add_argument("--model", default=gate_mod.DEFAULT_MODEL)
    parser.add_argument("--mock", action="store_true",
                        help="offline deterministic gate (pipeline validation)")
    parser.add_argument("--smoke", action="store_true",
                        help="1 task, 5 outputs, 2 proxies (spec section 8.2)")
    parser.add_argument("--sample", type=int, default=0, metavar="N",
                        help="additionally generate N real sampled outputs per "
                             "task at varied temperature (needs a key)")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    return parser.parse_args(argv)


def build_smoke_population(task) -> list:
    """Spec section 8.2: 1 reference, 2 mutated-wrong, 2 sampled."""
    outputs = [o for o in population.build_population(task)
               if o.origin == Origin.REFERENCE
               or (o.origin == Origin.MUTATED
                   and o.gold_meta.get("mutation") in SMOKE_MUTATIONS)]
    sampled = [o for o in population.build_population(task)
               if o.origin == Origin.SAMPLED][:2]
    return outputs + sampled


def main(argv=None) -> int:
    args = parse_args(argv)
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".cache"
    variants = ["holistic", "decomposed"] if args.gate == "both" else [args.gate]

    client = None
    judge = None
    if not args.mock:
        client = gate_mod.make_client()
        judge = gate_mod.make_proxy_judge(client, args.model)

    # --- tasks -------------------------------------------------------------
    all_tasks = gold.build_tasks()
    gold.sanity_check_all()
    if args.smoke:
        task_ids = [SMOKE_TASK]
    elif args.tasks == "all":
        task_ids = list(all_tasks)
    else:
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        unknown = [t for t in task_ids if t not in all_tasks]
        if unknown:
            raise SystemExit(f"unknown tasks: {unknown}; known: {list(all_tasks)}")

    # --- populations (gold-labeled) ---------------------------------------
    populations: dict[str, list] = {}
    balance: dict[str, dict] = {}
    for task_id in task_ids:
        task = all_tasks[task_id]
        if args.smoke:
            pop = build_smoke_population(task)
            balance[task_id] = population.balance_report(pop)
        else:
            pop = population.build_population(task)
            if args.sample and client is not None:
                pop.extend(population.sample_real_outputs(
                    task, client, args.model, n=args.sample))
            balance[task_id] = population.check_balance(task_id, pop)
        populations[task_id] = pop
        print(f"[population] {task_id}: {balance[task_id]}")

    # --- frozen proxy bank, then proxy results ----------------------------
    bank = proxy_bank.build_proxy_bank()
    proxies = []
    for task_id in task_ids:
        task_proxies = bank[task_id]
        if args.smoke:
            wanted = {f"{task_id}::{p}" for p in SMOKE_PROXIES}
            task_proxies = [p for p in task_proxies if p.proxy_id in wanted]
        proxies.extend(task_proxies)

    proxy_results = {}
    for proxy in proxies:
        result = proxy_bank.run_proxy(proxy, populations[proxy.task_id], judge=judge)
        proxy_results[proxy.proxy_id] = result
        print(f"[proxy] {proxy.proxy_id}: MCC {result.empirical_validity:+.2f}")

    # --- gate (sees ONLY task prompt + proxy definition) ------------------
    gate_scores: dict[str, dict[str, object]] = {v: {} for v in variants}
    for variant in variants:
        for proxy in proxies:
            score = gate_mod.gate_score(
                all_tasks[proxy.task_id].prompt,
                proxy.definition,
                variant=variant,
                model=args.model,
                votes=args.votes,
                cache_dir=cache_dir,
                mock=args.mock,
                client=client,
            )
            score.proxy_id = proxy.proxy_id
            gate_scores[variant][proxy.proxy_id] = score
            print(f"[gate:{variant}] {proxy.proxy_id}: "
                  f"{score.validity_score:.2f} (var {score.sample_variance:.4f})")

    # --- smoke sanity (spec section 8.2) ----------------------------------
    if args.smoke:
        variant = variants[0]
        valid_score = gate_scores[variant][f"{SMOKE_TASK}::{SMOKE_PROXIES[0]}"]
        irrel_score = gate_scores[variant][f"{SMOKE_TASK}::{SMOKE_PROXIES[1]}"]
        if valid_score.validity_score <= irrel_score.validity_score:
            print("SMOKE FAILURE: obviously-valid proxy did not outscore the "
                  f"obviously-irrelevant one ({valid_score.validity_score:.2f} "
                  f"<= {irrel_score.validity_score:.2f}) — debug before scaling "
                  "(spec section 8.2).", file=sys.stderr)
            return 1
        print(f"[smoke] OK: valid {valid_score.validity_score:.2f} > "
              f"irrelevant {irrel_score.validity_score:.2f}")

    # --- analysis rows -----------------------------------------------------
    rows = []
    for proxy in proxies:
        result = proxy_results[proxy.proxy_id]
        rows.append({
            "proxy_id": proxy.proxy_id,
            "task_id": proxy.task_id,
            "intended_class": proxy.intended_class.value,
            "kind": proxy.kind.value,
            "empirical_validity": result.empirical_validity,
            "balanced_accuracy": result.balanced_accuracy,
            "gate": {
                variant: {
                    "validity_score": gate_scores[variant][proxy.proxy_id].validity_score,
                    "sample_variance": gate_scores[variant][proxy.proxy_id].sample_variance,
                    "subjudgments": gate_scores[variant][proxy.proxy_id].subjudgments,
                }
                for variant in variants
            },
        })

    metrics_by_variant = {}
    if not args.smoke:
        for variant in variants:
            metrics_by_variant[variant] = analyze.compute_metrics(rows, variant)
            analyze.calibration_plot(
                rows, variant, out_dir / f"calibration_{variant}.png")

    # --- deliverables ------------------------------------------------------
    config = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mock": args.mock,
        "smoke": args.smoke,
        "gate_model": "mock" if args.mock else args.model,
        "votes": args.votes,
        "variants": variants,
        "task_ids": task_ids,
        "sampled_per_task": args.sample,
    }
    raw = {
        "config": config,
        "balance": balance,
        "tasks": {t: to_jsonable(all_tasks[t]) for t in task_ids},
        "outputs": {t: to_jsonable(populations[t]) for t in task_ids},
        "proxies": [
            {k: v for k, v in to_jsonable(p).items()
             if k not in ("impl", "mock_predicate")}
            for p in proxies
        ],
        "proxy_results": to_jsonable(proxy_results),
        "gate_scores": to_jsonable(gate_scores),
        "analysis_rows": rows,
        "metrics": metrics_by_variant,
    }
    (out_dir / "exp1_raw.json").write_text(
        json.dumps(raw, indent=1), encoding="utf-8")
    print(f"[write] {out_dir / 'exp1_raw.json'}")

    if not args.smoke:
        analyze.write_report(
            out_dir / "REPORT.md", rows, metrics_by_variant, balance, config)
        print(f"[write] {out_dir / 'REPORT.md'}")
        primary = "decomposed" if "decomposed" in metrics_by_variant else variants[0]
        call, reason = analyze.verdict(metrics_by_variant[primary])
        banner = " (MOCK — pipeline validation only)" if args.mock else ""
        print(f"\n=== VERDICT{banner}: {call} ===\n{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
