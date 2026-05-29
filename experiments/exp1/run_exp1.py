#!/usr/bin/env python3
from __future__ import annotations
"""
Experiment 1 orchestrator — Gold-Proxy Separation Harness.

Pipeline:
  build populations -> run gold -> run proxies (empirical_validity)
  -> run gate (holistic + decomposed, voting@3, blind) -> analyze -> write results.

Usage:
  python -m experiments.exp1.run_exp1 --smoke --mock          # 1 task, tiny, offline
  python -m experiments.exp1.run_exp1 --mock                  # full pipeline, offline
  ANTHROPIC_API_KEY=... python -m experiments.exp1.run_exp1 --tasks all --gate both
"""

import argparse
import json
from pathlib import Path

from . import analyze as A
from . import population as P
from . import proxy_bank as B
from .cache import Cache
from .gate import (DEFAULT_MODEL, decomposed_gate, holistic_gate, load_api_key,
                   make_client)

RESULTS = Path(__file__).resolve().parent / "results"


def make_judge(client, model, cache):
    """Build the llm_judged-proxy verdict function (real mode), cached."""
    def judge(prompt_template: str, output_text: str) -> bool:
        def compute():
            text = client.messages.create(
                model=model, max_tokens=10, temperature=0.0,
                messages=[{"role": "user",
                           "content": prompt_template.replace("{output}", output_text[:8000])}],
            ).content[0].text
            return "yes" in text.lower()
        return cache.get_or_compute(("judge", prompt_template, output_text), compute)
    return judge


def run(tasks_arg="all", gate_variant="both", mock=True, smoke=False,
        model=DEFAULT_MODEL, use_cache=True):
    client = None
    judge = None
    if not mock:
        key = load_api_key()
        if not key:
            raise SystemExit(
                "ANTHROPIC_API_KEY not set (and no .env / ~/.anthropic/api_key). "
                "Set it or run with --mock.")
        client = make_client()
        judge = make_judge(client, model, Cache("judge", use_cache))

    gate_cache = Cache("gate", use_cache and not mock)
    all_tasks = P.all_tasks()
    if smoke:
        selected = ["sql_ltv_top10"]
    elif tasks_arg in ("all", None):
        selected = list(all_tasks)
    else:
        selected = [t.strip() for t in tasks_arg.split(",")]

    raw = {"config": {"mock": mock, "smoke": smoke, "model": model,
                      "gate_variant": gate_variant, "tasks": selected},
           "tasks": {}, "pairs": []}

    variants = (["holistic", "decomposed"] if gate_variant == "both" else [gate_variant])

    for tid in selected:
        task = all_tasks[tid]
        population = P.build_population(task, smoke=smoke)
        bal = P.balance(population)
        proxies = B.build_proxy_bank(task)
        if smoke:
            proxies = [proxies[0], [p for p in proxies
                                    if p.intended_class.value == "irrelevant"][0]]

        task_rec = {"prompt": task.prompt, "family": task.family, "balance": bal,
                    "outputs": [{"output_id": o.output_id, "origin": o.origin.value,
                                 "gold_verdict": o.gold_verdict, "gold_meta": o.gold_meta}
                                for o in population],
                    "proxy_results": [], "gate_scores": []}

        for proxy in proxies:
            pres = B.run_proxy(proxy, population, mock=mock, judge=judge)
            task_rec["proxy_results"].append({
                "proxy_id": proxy.proxy_id, "kind": proxy.kind.value,
                "intended_class": proxy.intended_class.value,
                "definition": proxy.definition,
                "empirical_validity": pres.empirical_validity,
                "balanced_accuracy": pres.balanced_accuracy,
                "per_output_verdicts": pres.per_output_verdicts,
                "n_outputs": pres.n_outputs})

            pair = {"task_id": tid, "proxy_id": proxy.proxy_id,
                    "kind": proxy.kind.value, "intended_class": proxy.intended_class.value,
                    "empirical_validity": pres.empirical_validity}

            # GATE — receives ONLY task.prompt and proxy.definition (integrity by signature).
            for variant in variants:
                fn = holistic_gate if variant == "holistic" else decomposed_gate
                gs = gate_cache.get_or_compute(
                    (variant, model, task.prompt, proxy.definition),
                    lambda fn=fn, variant=variant: _gatescore_to_dict(
                        fn(task.prompt, proxy.definition, proxy_id=proxy.proxy_id,
                           task_id=tid, client=client, model=model, mock=mock)))
                if isinstance(gs, dict):
                    score = gs["validity_score"]
                    task_rec["gate_scores"].append(gs)
                else:
                    score = gs
                pair[f"{variant}_score"] = score

            raw["pairs"].append(pair)

        raw["tasks"][tid] = task_rec

    # Analysis
    analysis = A.analyze(raw["pairs"])
    raw["analysis"] = analysis

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "exp1_raw.json").write_text(json.dumps(raw, indent=2, default=str))

    # Plots
    plot_paths = {}
    for variant in variants:
        key = f"{variant}_score"
        usable = [p for p in raw["pairs"] if key in p]
        if usable:
            path = RESULTS / f"calibration_{variant}.png"
            A.plot_calibration(usable, key, f"Gate calibration — {variant}"
                               + (" (MOCK)" if mock else ""), path)
            plot_paths[variant] = path.name

    write_report(raw, analysis, plot_paths, mock)
    return raw, analysis


def _gatescore_to_dict(gs):
    return {"proxy_id": gs.proxy_id, "task_id": gs.task_id,
            "validity_score": gs.validity_score, "rationale": gs.rationale,
            "gate_model": gs.gate_model, "variant": gs.variant,
            "subjudgments": gs.subjudgments, "samples": gs.samples,
            "sample_variance": gs.sample_variance}


def _fmt(v, nd=2):
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return str(v)


def _ci(ci):
    if not ci:
        return "n/a"
    return f"[{_fmt(ci[0])}, {_fmt(ci[1])}]"


def write_report(raw, analysis, plot_paths, mock):
    lines = []
    bv = analysis.get("by_variant", {})
    # Headline = holistic if present else first variant
    head_variant = "holistic" if "holistic" in bv else (next(iter(bv)) if bv else None)
    if head_variant:
        m = bv[head_variant]
        dec = analysis["decision"].get(head_variant, "AMBIGUOUS")
        lines.append(f"# Experiment 1 — VERDICT: {dec}"
                     + ("  *(MOCK GATE — numbers are pipeline-validation only)*" if mock else ""))
        lines.append("")
        lines.append(f"**{head_variant} gate:** Spearman ρ = {_fmt(m['spearman_rho'])} "
                     f"(95% CI {_ci(m['spearman_ci95'])}), AUROC = {_fmt(m['auroc'])} "
                     f"(95% CI {_ci(m['auroc_ci95'])}), over n={m['n']} proxies.")
        lines.append(f"Decision rule: GREENLIGHT if ρ≥0.5 AND AUROC≥0.75; "
                     f"KILL if ρ≤0.2 OR AUROC≤0.6.")
    else:
        lines.append("# Experiment 1 — VERDICT: AMBIGUOUS (no metrics)")
    lines.append("")

    if mock:
        lines.append("> ⚠️ This run used the **mock gate** (no `ANTHROPIC_API_KEY`). The gold, "
                     "populations, mutations, proxy empirical-validity (MCC), bootstrap and "
                     "plotting are all real and exercised; the gate scores are deterministic "
                     "heuristics, so ρ/AUROC here only prove the plumbing. Re-run with a key "
                     "for the real verdict.")
        lines.append("")

    # Per-variant headline table
    lines.append("## Headline metrics by gate variant")
    lines.append("")
    lines.append("| Variant | n | Spearman ρ | ρ 95% CI | AUROC | AUROC 95% CI | Decision |")
    lines.append("|---|---|---|---|---|---|---|")
    for variant, m in bv.items():
        lines.append(f"| {variant} | {m['n']} | {_fmt(m['spearman_rho'])} | {_ci(m['spearman_ci95'])} "
                     f"| {_fmt(m['auroc'])} | {_ci(m['auroc_ci95'])} "
                     f"| {analysis['decision'].get(variant,'?')} |")
    lines.append("")

    # Confounded recall
    lines.append("## Confounded-class recall (the key diagnostic)")
    lines.append("Of proxies the author labeled *confounded* whose empirical validity came out "
                 "low, what fraction did the gate also score low (<0.5)? Catching these is the "
                 "whole product.")
    lines.append("")
    for variant, cr in analysis.get("confounded_recall", {}).items():
        lines.append(f"- **{variant}**: recall = {_fmt(cr['recall'])} (n={cr['n']})")
    lines.append("")

    # executable vs llm_judged
    lines.append("## Executable vs LLM-judged proxies")
    lines.append("")
    for variant, byk in analysis.get("by_kind", {}).items():
        for kind, m in byk.items():
            lines.append(f"- **{variant} / {kind}** (n={m['n']}): ρ={_fmt(m['spearman_rho'])}, "
                         f"AUROC={_fmt(m['auroc'])}")
    lines.append("")

    # Per-task
    lines.append("## Per-task breakdown")
    lines.append("")
    lines.append("| Task | Variant | n | ρ | AUROC | balance (pass/total) |")
    lines.append("|---|---|---|---|---|---|")
    for variant, byt in analysis.get("by_task", {}).items():
        for tid, m in byt.items():
            bal = raw["tasks"][tid]["balance"]
            lines.append(f"| {tid} | {variant} | {m['n']} | {_fmt(m['spearman_rho'])} "
                         f"| {_fmt(m['auroc'])} | {bal['n_pass']}/{bal['n']} |")
    lines.append("")

    # Calibration plots
    if plot_paths:
        lines.append("## Calibration plots")
        for variant, name in plot_paths.items():
            lines.append(f"### {variant}")
            lines.append(f"![calibration {variant}]({name})")
        lines.append("")

    # Caveat
    lines.append("## Caveat (do not over-update)")
    lines.append("A positive result here means the gate works **where ground truth exists** "
                 "(executable SQL / JSON-schema). That is a *necessary, not sufficient* "
                 "condition for the product. Experiment 2 — adversarial confounded-vs-valid "
                 "pairs in genuinely ungrounded domains — is the real test.")
    lines.append("")
    lines.append("All numbers are reconstructable from `exp1_raw.json`.")

    (RESULTS / "REPORT.md").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="all",
                    help="comma-separated task ids, or 'all'")
    ap.add_argument("--gate", default="both", choices=["holistic", "decomposed", "both"])
    ap.add_argument("--mock", action="store_true", help="run offline with deterministic gate")
    ap.add_argument("--smoke", action="store_true", help="tiny 1-task pipeline check")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    raw, analysis = run(tasks_arg=args.tasks, gate_variant=args.gate, mock=args.mock,
                        smoke=args.smoke, model=args.model, use_cache=not args.no_cache)

    bv = analysis.get("by_variant", {})
    print(f"\nWrote {RESULTS/'REPORT.md'} and {RESULTS/'exp1_raw.json'}")
    for variant, m in bv.items():
        print(f"  {variant}: rho={_fmt(m['spearman_rho'])} auroc={_fmt(m['auroc'])} "
              f"-> {analysis['decision'].get(variant)}")


if __name__ == "__main__":
    main()
