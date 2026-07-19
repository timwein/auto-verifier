"""Metrics, plots, and REPORT.md (SPEC.md section 6).

Primary: Spearman rho(gate_score, empirical_validity) and AUROC of the gate
separating empirically-valid (MCC >= 0.5) from invalid proxies, both with
bootstrap 95% CIs (resampling proxies with replacement). Secondary: holistic
vs decomposed, executable vs llm_judged, confounded-class recall, per-task
breakdown, calibration plot. ~40 points is thin: CIs are reported everywhere
and the verdict logic refuses to over-claim (spec section 9).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import stats

VALID_THRESHOLD = 0.5  # empirical_validity >= this -> "empirically valid"
BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 20260719

# Decision rule (SPEC.md section 0).
GREEN_RHO, GREEN_AUROC = 0.5, 0.75
KILL_RHO, KILL_AUROC = 0.2, 0.6


def spearman_rho(gate_scores: list[float], validities: list[float]) -> float:
    if len(set(gate_scores)) < 2 or len(set(validities)) < 2:
        return 0.0
    rho, _ = stats.spearmanr(gate_scores, validities)
    return float(rho)


def auroc(gate_scores: list[float], is_valid: list[bool]) -> float:
    """Mann-Whitney AUROC with tie credit 0.5; None-ish 0.5 when degenerate."""
    pos = [s for s, v in zip(gate_scores, is_valid) if v]
    neg = [s for s, v in zip(gate_scores, is_valid) if not v]
    if not pos or not neg:
        return 0.5
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def bootstrap_ci(
    values_x: list[float],
    values_y: list,
    stat_fn,
    iters: int = BOOTSTRAP_ITERS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, int]:
    """Percentile CI, resampling (x, y) pairs with replacement. Degenerate
    resamples (single class / constant vector) are skipped and counted."""
    rng = np.random.default_rng(seed)
    n = len(values_x)
    stats_out = []
    skipped = 0
    for _ in range(iters):
        idx = rng.integers(0, n, size=n)
        xs = [values_x[i] for i in idx]
        ys = [values_y[i] for i in idx]
        if _degenerate(xs, ys):
            skipped += 1
            continue
        stats_out.append(stat_fn(xs, ys))
    if not stats_out:
        return float("nan"), float("nan"), skipped
    lo, hi = np.percentile(stats_out, [2.5, 97.5])
    return float(lo), float(hi), skipped


def _degenerate(xs: list, ys: list) -> bool:
    if isinstance(ys[0], bool):
        return len(set(ys)) < 2
    return len(set(xs)) < 2 or len(set(ys)) < 2


def confounded_recall(rows: list[dict], variant: str) -> tuple[float, int]:
    """Of author-labeled confounded proxies whose empirical validity came out
    low, what fraction did the gate score low? The headline diagnostic."""
    crux = [
        r for r in rows
        if r["intended_class"] == "confounded"
        and r["empirical_validity"] < VALID_THRESHOLD
    ]
    if not crux:
        return float("nan"), 0
    caught = sum(1 for r in crux if r["gate"][variant]["validity_score"] < 0.5)
    return caught / len(crux), len(crux)


def compute_metrics(rows: list[dict], variant: str) -> dict:
    gate_scores = [r["gate"][variant]["validity_score"] for r in rows]
    validities = [r["empirical_validity"] for r in rows]
    labels = [v >= VALID_THRESHOLD for v in validities]
    rho = spearman_rho(gate_scores, validities)
    rho_lo, rho_hi, rho_skip = bootstrap_ci(gate_scores, validities, spearman_rho)
    auc = auroc(gate_scores, labels)
    auc_lo, auc_hi, auc_skip = bootstrap_ci(gate_scores, labels, auroc)
    recall, crux_n = confounded_recall(rows, variant)
    return {
        "n": len(rows),
        "spearman_rho": rho,
        "rho_ci": [rho_lo, rho_hi],
        "rho_bootstrap_skipped": rho_skip,
        "auroc": auc,
        "auroc_ci": [auc_lo, auc_hi],
        "auroc_bootstrap_skipped": auc_skip,
        "confounded_recall": recall,
        "confounded_crux_n": crux_n,
        "mean_sample_variance": float(
            np.mean([r["gate"][variant]["sample_variance"] for r in rows])
        ),
    }


def verdict(metrics: dict) -> tuple[str, str]:
    """Apply the section-0 decision rule; returns (verdict, reason)."""
    rho, (rho_lo, _) = metrics["spearman_rho"], metrics["rho_ci"]
    auc, (auc_lo, _) = metrics["auroc"], metrics["auroc_ci"]
    if rho <= KILL_RHO or auc <= KILL_AUROC:
        return "KILL", (
            f"rho={rho:.3f} <= {KILL_RHO} or AUROC={auc:.3f} <= {KILL_AUROC}: "
            "the gate cannot do the easy case; it will not do the hard one."
        )
    if (
        rho >= GREEN_RHO
        and auc >= GREEN_AUROC
        and rho_lo > KILL_RHO
        and auc_lo > KILL_AUROC
    ):
        return "GREENLIGHT", (
            f"rho={rho:.3f} >= {GREEN_RHO} and AUROC={auc:.3f} >= {GREEN_AUROC}, "
            f"with bootstrap CIs (rho lower {rho_lo:.3f}, AUROC lower {auc_lo:.3f}) "
            "excluding the kill thresholds."
        )
    return "AMBIGUOUS", (
        f"rho={rho:.3f} (CI lower {rho_lo:.3f}), AUROC={auc:.3f} (CI lower "
        f"{auc_lo:.3f}): between kill and greenlight, or CIs cross the kill "
        "thresholds. Proceed to Experiment 2 with tempered expectations."
    )


def split_metrics(rows: list[dict], variant: str, key: str) -> dict[str, dict]:
    out = {}
    for value in sorted({r[key] for r in rows}):
        subset = [r for r in rows if r[key] == value]
        if len(subset) >= 3:
            out[value] = compute_metrics(subset, variant)
        else:
            out[value] = {"n": len(subset), "note": "too few rows for metrics"}
    return out


def calibration_plot(rows: list[dict], variant: str, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"valid": "#2a9d3a", "confounded": "#e07b00", "irrelevant": "#888888"}
    markers = {"executable": "o", "llm_judged": "^"}
    fig, ax = plt.subplots(figsize=(7.5, 6))
    for r in rows:
        ax.scatter(
            r["gate"][variant]["validity_score"],
            r["empirical_validity"],
            c=colors[r["intended_class"]],
            marker=markers[r["kind"]],
            s=70,
            edgecolors="black",
            linewidths=0.5,
            alpha=0.85,
        )
    ax.axhline(VALID_THRESHOLD, color="#bbb", ls="--", lw=1)
    ax.axvline(0.5, color="#bbb", ls="--", lw=1)
    ax.set_xlabel(f"gate validity_score ({variant})")
    ax.set_ylabel("empirical validity (MCC vs gold)")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-1.05, 1.05)
    ax.set_title(f"Gate calibration — {variant} (color=intended class, shape=kind)")
    handles = [
        plt.Line2D([], [], marker="o", ls="", color=c, label=lbl)
        for lbl, c in colors.items()
    ] + [
        plt.Line2D([], [], marker=m, ls="", color="black", label=lbl)
        for lbl, m in markers.items()
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# REPORT.md — verdict first (spec section 7).
# ---------------------------------------------------------------------------


def _fmt(metrics: dict) -> str:
    return (
        f"rho **{metrics['spearman_rho']:+.3f}** "
        f"(95% CI [{metrics['rho_ci'][0]:+.3f}, {metrics['rho_ci'][1]:+.3f}]), "
        f"AUROC **{metrics['auroc']:.3f}** "
        f"(95% CI [{metrics['auroc_ci'][0]:.3f}, {metrics['auroc_ci'][1]:.3f}]), "
        f"n={metrics['n']}"
    )


def write_report(
    path: Path,
    rows: list[dict],
    metrics_by_variant: dict[str, dict],
    balance: dict[str, dict],
    config: dict,
) -> None:
    primary_variant = "decomposed" if "decomposed" in metrics_by_variant else next(
        iter(metrics_by_variant)
    )
    primary = metrics_by_variant[primary_variant]
    call, reason = verdict(primary)
    mock = config.get("mock", False)

    lines: list[str] = []
    if mock:
        lines += [
            "> **MOCK RUN — pipeline validation only.** The gate scores below come "
            "from the deterministic offline mock, not a model. This is NOT an "
            "experimental verdict; run with an API key for the real one.",
            "",
        ]
    lines += [
        f"# Experiment 1 verdict: {call}",
        "",
        f"**{reason}**",
        "",
        f"Primary variant: {primary_variant} gate — {_fmt(primary)}.",
        "Decision rule (SPEC.md section 0): greenlight iff rho >= 0.5 AND AUROC >= 0.75 "
        "with CIs excluding the kill thresholds (rho <= 0.2, AUROC <= 0.6).",
        "",
        "## Headline numbers",
        "",
        "| gate variant | Spearman rho [95% CI] | AUROC [95% CI] | confounded-class recall | mean vote variance |",
        "|---|---|---|---|---|",
    ]
    for variant, m in metrics_by_variant.items():
        recall = (
            f"{m['confounded_recall']:.2f} (n={m['confounded_crux_n']})"
            if m["confounded_crux_n"]
            else "n/a"
        )
        lines.append(
            f"| {variant} | {m['spearman_rho']:+.3f} "
            f"[{m['rho_ci'][0]:+.3f}, {m['rho_ci'][1]:+.3f}] | "
            f"{m['auroc']:.3f} [{m['auroc_ci'][0]:.3f}, {m['auroc_ci'][1]:.3f}] | "
            f"{recall} | {m['mean_sample_variance']:.4f} |"
        )
    lines += [
        "",
        "**Confounded-class recall** — of proxies the author labeled confounded "
        "whose empirical validity came out low, the fraction the gate scored "
        "below 0.5. Catching confounded proxies is the whole product; this is "
        "the single most important diagnostic (small n, read with care).",
        "",
        "## Calibration",
        "",
    ]
    for variant in metrics_by_variant:
        lines.append(f"![calibration {variant}](calibration_{variant}.png)")
    lines += [
        "",
        "A gate that tracks truth shows an upward trend; a guessing gate is a "
        "cloud. Orange (confounded) points in the lower-right quadrant are "
        "gate failures on the crux cases.",
        "",
        "## Executable vs llm_judged proxies",
        "",
    ]
    for variant, m in metrics_by_variant.items():
        lines.append(f"**{variant}:**")
        for kind, km in split_metrics(rows, variant, "kind").items():
            if "note" in km:
                lines.append(f"- {kind}: {km['note']} (n={km['n']})")
            else:
                lines.append(f"- {kind}: {_fmt(km)}")
        lines.append("")
    lines += ["## Per-task breakdown", ""]
    for variant, m in metrics_by_variant.items():
        lines.append(f"**{variant}:**")
        lines.append("")
        lines.append("| task | rho | AUROC | n |")
        lines.append("|---|---|---|---|")
        for task_id, tm in split_metrics(rows, variant, "task_id").items():
            if "note" in tm:
                lines.append(f"| {task_id} | - | - | {tm['n']} |")
            else:
                lines.append(
                    f"| {task_id} | {tm['spearman_rho']:+.3f} | "
                    f"{tm['auroc']:.3f} | {tm['n']} |"
                )
        lines.append("")
    lines += [
        "## Population balance (spec section 3)",
        "",
        "| task | outputs | gold pass | gold fail | pass rate |",
        "|---|---|---|---|---|",
    ]
    for task_id, b in balance.items():
        lines.append(
            f"| {task_id} | {b['n']} | {b['pass']} | {b['fail']} | {b['pass_rate']} |"
        )
    lines += [
        "",
        "## Per-proxy detail",
        "",
        "| proxy | class | kind | empirical validity (MCC) | "
        + " | ".join(f"gate {v}" for v in metrics_by_variant)
        + " |",
        "|---|---|---|---|" + "---|" * len(metrics_by_variant),
    ]
    for r in sorted(rows, key=lambda r: (r["task_id"], -r["empirical_validity"])):
        gates = " | ".join(
            f"{r['gate'][v]['validity_score']:.2f}" for v in metrics_by_variant
        )
        lines.append(
            f"| {r['proxy_id']} | {r['intended_class']} | {r['kind']} | "
            f"{r['empirical_validity']:+.2f} | {gates} |"
        )
    lines += [
        "",
        "## Caveats (spec section 9)",
        "",
        f"- Thin n ({primary['n']} proxy datapoints): CIs are wide by design; do "
        "not over-read the point estimates. A clearly-positive or clearly-null "
        "result is trustworthy at this n; a marginal one is not.",
        "- **Easy-case caveat**: a positive result means the gate works where "
        "ground truth exists. Necessary, not sufficient — Experiment 2 "
        "(adversarial confounded-vs-valid pairs in genuinely ungrounded "
        "domains) is the real test. Do not over-update on a greenlight.",
        "- Gold trustworthiness was spot-checked in code: reference outputs "
        "pass, every breaking mutation fails, every surface mutation passes "
        "(tests/test_exp1.py).",
    ]
    if mock:
        lines += [
            "- This was a MOCK run: gate scores are a deterministic keyword "
            "heuristic, present only to validate the pipeline end to end.",
        ]
    lines += [
        "",
        f"Config: {json.dumps({k: v for k, v in config.items() if k != 'tasks'})}",
        "",
        "Every number above is reconstructable from `exp1_raw.json`.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
