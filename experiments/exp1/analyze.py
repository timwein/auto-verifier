#!/usr/bin/env python3
from __future__ import annotations
"""
Metrics + plots for Experiment 1 (spec section 6).

Operates over (task, proxy) pairs, each carrying:
  empirical_validity (MCC vs gold), and the gate's validity_score per variant,
  plus kind (executable|llm_judged) and intended_class (analysis only).

Primary:  Spearman rho(gate_score, empirical_validity); AUROC separating
          valid (empirical_validity >= VALID_THRESHOLD) from not.
Secondary: holistic vs decomposed; executable vs llm_judged; confounded-class
          recall; per-task; calibration plot; bootstrap 95% CIs.
"""

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

VALID_THRESHOLD = 0.5
# Section-0 decision thresholds
GREENLIGHT_RHO, GREENLIGHT_AUROC = 0.5, 0.75
KILL_RHO, KILL_AUROC = 0.2, 0.6


def _spearman(x, y):
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return float("nan")
    return float(spearmanr(x, y).correlation)


def _auroc(scores, labels):
    if len(set(labels)) < 2:
        return float("nan")
    return float(roc_auc_score(labels, scores))


def bootstrap_metric(values_x, values_y, labels, metric="spearman",
                     n_iter=1000, seed=0):
    """Bootstrap a metric by resampling pairs with replacement."""
    rng = np.random.default_rng(seed)
    x = np.asarray(values_x, float)
    y = np.asarray(values_y, float)
    lab = np.asarray(labels, int)
    n = len(x)
    out = []
    for _ in range(n_iter):
        idx = rng.integers(0, n, n)
        if metric == "spearman":
            v = _spearman(x[idx], y[idx])
        else:  # auroc: x are gate scores, lab are labels
            v = _auroc(x[idx], lab[idx])
        if not np.isnan(v):
            out.append(v)
    if not out:
        return (float("nan"), float("nan"))
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def _metrics_for(pairs, score_key):
    emp = [p["empirical_validity"] for p in pairs]
    gate = [p[score_key] for p in pairs]
    labels = [1 if e >= VALID_THRESHOLD else 0 for e in emp]
    rho = _spearman(gate, emp)
    auroc = _auroc(gate, labels)
    rho_ci = bootstrap_metric(gate, emp, labels, "spearman")
    auroc_ci = bootstrap_metric(gate, emp, labels, "auroc")
    return {"n": len(pairs), "spearman_rho": rho, "spearman_ci95": rho_ci,
            "auroc": auroc, "auroc_ci95": auroc_ci,
            "n_valid": sum(labels), "n_invalid": len(labels) - sum(labels)}


def confounded_recall(pairs, score_key):
    """Of proxies labeled 'confounded' whose empirical_validity is low (< threshold),
    what fraction did the gate also score low (< 0.5)?"""
    targets = [p for p in pairs if p["intended_class"] == "confounded"
               and p["empirical_validity"] < VALID_THRESHOLD]
    if not targets:
        return {"n": 0, "recall": float("nan")}
    caught = sum(1 for p in targets if p[score_key] < 0.5)
    return {"n": len(targets), "recall": caught / len(targets)}


def verdict(rho, auroc):
    if rho is None or np.isnan(rho) or auroc is None or np.isnan(auroc):
        return "AMBIGUOUS (insufficient/degenerate data)"
    if rho >= GREENLIGHT_RHO and auroc >= GREENLIGHT_AUROC:
        return "GREENLIGHT"
    if rho <= KILL_RHO or auroc <= KILL_AUROC:
        return "KILL / RETHINK"
    return "AMBIGUOUS"


def analyze(pairs):
    """pairs: list of dicts with keys empirical_validity, holistic_score,
    decomposed_score, kind, intended_class, task_id, proxy_id."""
    result = {"overall": {}, "by_variant": {}, "by_kind": {}, "by_task": {},
              "confounded_recall": {}, "decision": {}}

    for variant, key in [("holistic", "holistic_score"), ("decomposed", "decomposed_score")]:
        usable = [p for p in pairs if key in p and p[key] is not None]
        if not usable:
            continue
        result["by_variant"][variant] = _metrics_for(usable, key)
        result["confounded_recall"][variant] = confounded_recall(usable, key)
        for kind in ("executable", "llm_judged"):
            sub = [p for p in usable if p["kind"] == kind]
            if len(sub) >= 3:
                result["by_kind"].setdefault(variant, {})[kind] = _metrics_for(sub, key)
        for tid in sorted({p["task_id"] for p in usable}):
            sub = [p for p in usable if p["task_id"] == tid]
            result["by_task"].setdefault(variant, {})[tid] = _metrics_for(sub, key)

    # Headline = best available variant (prefer holistic for the primary number,
    # but report both); decision computed per variant.
    for variant in result["by_variant"]:
        m = result["by_variant"][variant]
        result["decision"][variant] = verdict(m["spearman_rho"], m["auroc"])

    return result


def plot_calibration(pairs, score_key, title, path):
    colors = {"valid": "tab:green", "confounded": "tab:orange", "irrelevant": "tab:red"}
    plt.figure(figsize=(6, 6))
    for cls, col in colors.items():
        xs = [p[score_key] for p in pairs if p["intended_class"] == cls]
        ys = [p["empirical_validity"] for p in pairs if p["intended_class"] == cls]
        plt.scatter(xs, ys, c=col, label=cls, alpha=0.8, edgecolors="k", linewidths=0.4)
    plt.axhline(VALID_THRESHOLD, ls="--", c="gray", lw=0.8)
    plt.axvline(0.5, ls="--", c="gray", lw=0.8)
    plt.xlabel("gate validity_score (a priori, blind)")
    plt.ylabel("empirical_validity (MCC vs gold)")
    plt.title(title)
    plt.xlim(-0.02, 1.02)
    plt.ylim(-1.05, 1.05)
    plt.legend()
    plt.grid(alpha=0.2)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()
