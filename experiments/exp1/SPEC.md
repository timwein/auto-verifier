# Experiment 1: Gold-Proxy Separation Harness

**For: Claude Code, executing inside the `auto-verifier` repo.**
**Goal: a one-to-two-day kill/greenlight signal on whether an automated construct-validity gate can tell a valid proxy check from a confounded one, measured where ground truth exists.**

-----

## 0. The question this answers (read first)

We are considering building a “Groundedness Constructor” whose load-bearing component is a **construct-validity gate**: given a claim C and a proposed check K, decide whether “K fails” actually implies “C is wrong.” The whole product dies if that gate cannot distinguish a *valid* proxy from a *plausible-but-confounded* one.

We cannot test the gate directly in the ungrounded domains it targets (no ground truth there, by construction). So we test it where ground truth **does** exist: the repo’s deterministic-verifier tasks (SQL, JSON schema, code with executable checks). The deterministic verifier is the **gold**. A manufactured check is a **proxy**. We measure whether the gate can predict, *a priori and blind to the gold*, which proxies actually track the gold.

This mirrors Gao et al. “Scaling Laws for Reward Model Overoptimization” (arXiv 2210.10760): a fixed gold signal stands in for truth, and we study how a proxy diverges from it. Here we add the prediction step: can a gate forecast the divergence before it happens.

**Decision rule (compute these, report them, do not bury them):**

- **Greenlight** to Experiment 2 if Spearman rho(gate_score, empirical_validity) >= 0.5 AND AUROC(gate separating valid vs invalid proxies) >= 0.75, with bootstrap CIs that exclude the kill thresholds.
- **Kill / rethink** if Spearman rho <= 0.2 OR AUROC <= 0.6. The gate cannot do the easy case; it will not do the hard one.
- **Ambiguous** in between: proceed to Experiment 2 but with tempered expectations and a note on which proxy classes the gate failed.

(These thresholds are proposed, not sacred. Surface the raw numbers so a human can re-judge.)

-----

## 1. Definitions (the data model)

Implement these as dataclasses in `experiments/exp1/models.py`. Reuse enums/types from the repo’s `rubric_system/models.py` where they already exist; do not duplicate.

- **GroundedTask**: a task from the existing suite that has a deterministic verifier. Fields: `task_id`, `prompt`, `reference_output`, `gold_verifier_ref` (handle to the deterministic check).
- **Output**: one candidate output for a task. Fields: `task_id`, `text`, `origin` (one of `reference` | `sampled` | `mutated`), `gold_verdict` (bool or float in [0,1] from the deterministic verifier), `gold_meta` (e.g., which mutation was applied).
- **ProxyCheck**: a manufactured check that claims to verify “this output is correct.” Fields: `proxy_id`, `task_id`, `definition` (natural-language spec of what the check asserts), `kind` (`executable` | `llm_judged`), `intended_class` (`valid` | `confounded` | `irrelevant`, author’s label, used only for stratified analysis, never shown to the gate), `impl` (executable predicate or the judge prompt).
- **ProxyResult**: result of running a proxy over the output population. Fields: `proxy_id`, `per_output_verdicts`, `empirical_validity` (see section 4), `n_outputs`.
- **GateScore**: the gate’s a-priori judgment. Fields: `proxy_id`, `validity_score` in [0,1], `rationale`, `gate_model`, `subjudgments` (optional, for the decomposed variant in section 5).

-----

## 2. Repo integration (inspect before writing)

Before implementing, **inspect and summarize** these files into `experiments/exp1/DESIGN_NOTES.md` so we know the real interfaces (do not assume my descriptions are exact):

- `rubric_system/deterministic_verifier.py` — the gold. Find the call signature for scoring a code/SQL/schema output deterministically. This is the gold_verdict source. **Load-bearing assumption to verify: deterministic verifiers exist and return a trustworthy correct/incorrect signal for at least SQL and JSON-schema tasks.** If they only partially exist, note which tasks are usable.
- `rubric_system/scoring_engine.py` — reuse the model-call plumbing for the gate (the LLM that scores proxy validity). Do not build a new Anthropic client; wrap the existing one.
- `rubric_system/models.py` — reuse dataclasses/enums.
- `tasks/` and `sample_rubrics.py` — source the grounded task prompts and reference outputs.
- `EVAL.md` — confirm which tasks had deterministic verifiers active (Run 11 “Fix 7: Deterministic bash/SQL verifiers” is the signal).

Record any deviations from this spec forced by the actual code in DESIGN_NOTES.md. Deviating to match reality is correct; silently guessing is not.

-----

## 3. Tasks and the output population

**Pick 4 grounded tasks** where the deterministic verifier gives a clean correct/incorrect signal cheaply. Recommended (adjust to what actually has verifiers):

1. `sql_ltv_query` — execute against a seeded SQLite DB; gold = correct top-10-by-LTV result set.
1. `billing_schema` — validate held-out JSON instances against the produced schema; gold = accepts all valid instances, rejects all invalid ones.
1. `csv_parser` — run on a fixed set of messy-CSV test inputs; gold = correct parsed output.
1. One code task (`api_rate_limiter` or `rust_concurrent_cache`) **only if** a runnable test harness is cheap; otherwise substitute a second SQL or schema variant. Do not burn the budget standing up Rust toolchains for Exp 1.

**Build a labeled output population per task (target 30-60 outputs each):**

- A handful of `sampled` outputs: generate from the model at varied temperature so quality spans correct to wrong.
- A larger set of `mutated` outputs: take the reference correct output and apply **known, deterministic mutations** that flip correctness in specific ways (e.g., SQL: drop the ORDER BY, change DESC to ASC, wrong LIMIT, wrong join key, wrong aggregation; schema: loosen a required field, wrong type, missing constraint). Record the mutation in `gold_meta`.
- Keep the `reference` output as a known-correct anchor.

Run the gold verifier over the whole population to assign `gold_verdict`. **The population must contain both passes and fails, ideally not wildly imbalanced**, or the validity metrics are meaningless. Check and report the pass/fail balance per task; resample/mutate to fix gross imbalance.

Mutations matter because they are how we create *confounded* situations on purpose: a mutation that breaks correctness while leaving surface features intact is exactly what a confounded proxy will miss. This is the mechanism that makes the experiment discriminating.

-----

## 4. The proxy bank (the core authored artifact)

For each task author **8-12 proxy checks** spanning three classes. The class label is the author’s hypothesis; the *empirical* validity is computed, not assumed. Aim for a spread, not all-easy.

- **`valid`** proxies: checks that genuinely track correctness (often close to or a subset of the gold check). Example (SQL): “execute and assert the result set equals the reference result set.”
- **`confounded`** proxies: checks that correlate with correctness on typical outputs but **decouple under the mutations**. Example (SQL): “assert the query text contains ORDER BY … DESC and LIMIT 10.” Passes for many wrong queries (wrong join, wrong LTV formula) that happen to have the right clauses. These are the crux cases.
- **`irrelevant`** proxies: checks with near-zero causal link to correctness. Example: “assert the query is under 20 lines” or “uses a CTE.”

Author discipline (this protects the experiment’s own construct validity):

- Author the proxy bank **before** running the gate. No peeking at gate scores while writing proxies.
- Author proxies **without** looking at per-output gold verdicts (you may use the reference output and task spec). Otherwise you leak the answer into the proxy design.
- Mix `executable` and `llm_judged` proxies and record `kind`. Executable proxies are the clean floor; `llm_judged` proxies (a prompt that asks a model to check the predicate) are the realistic product case. Analyze them separately in section 6.

**empirical_validity(proxy)** = Matthews correlation coefficient (MCC) between the proxy’s per-output verdicts and the gold verdicts across the population. Range [-1, 1]. Also store balanced accuracy. MCC, not raw accuracy, because populations may be imbalanced. This number is the proxy’s *true* quality and the target the gate is trying to predict.

-----

## 5. The gate under test

The gate is an LLM that, given **only** `(task.prompt, proxy.definition)`, outputs a `validity_score` in [0,1] and a rationale. It is the thing we are evaluating.

**Hard integrity constraint: the gate never sees the output population, the per-output verdicts, the gold verifier, the mutations, or the author’s `intended_class`.** It must predict validity a priori from the claim and the check definition alone. Violating this turns the experiment into leakage and invalidates the result. Enforce it in code (the gate function signature literally cannot receive those fields).

Build two gate variants so we test Bet C while we are here:

1. **Holistic gate**: single prompt, “how valid a proxy is this check for verifying the claim, 0-1, with reasoning.” One score.
1. **Decomposed gate** (the promising direction): score sub-judgments separately and aggregate. Sub-judgments to include:
- *Causal coupling*: under what conditions does the check pass while the claim is false? (the confounder probe)
- *Externality*: does the check appeal to something outside the artifact’s own assertions?
- *Contradiction*: does “check fails” logically entail “claim false,” or only correlate?
- Aggregate to a single score (start with a simple mean or min; record sub-scores for analysis).
  This is the analytic-rubric pattern (cf. Autorubric, arXiv 2603.00077): per-criterion scoring with separable reliability.

Gate model: use the repo’s default (Sonnet) for Exp 1. Cross-family judges (GPT, Gemini) are an **optional** extension, not required for the kill/greenlight; Exp 1 tests capability existence, not monoculture. Run the gate with `voting@3` (median of 3 samples) to damp judge non-determinism, and record per-sample variance (SAGE, arXiv 2512.16041, warns judges destabilize on close cases; we want to see that).

-----

## 6. Metrics and analysis

Compute over all `(task, proxy)` pairs (~40 datapoints; thin, so bootstrap everything):

**Primary**

- **Spearman rho** between `gate_score` and `empirical_validity`. The headline number.
- **AUROC**: binarize proxies as valid (`empirical_validity >= 0.5`) vs not; how well does `gate_score` separate them.

**Secondary / diagnostic**

- Both metrics computed **separately for holistic vs decomposed** gate. Does decomposition beat holistic? (Bet C.)
- Both metrics **separately for executable vs llm_judged** proxies. We expect the gate to do better on cleaner proxies; the gap is informative.
- **Confounded-class recall**: of proxies the author labeled `confounded` and whose empirical_validity came out low, what fraction did the gate score low? This is the single most important diagnostic: catching confounded proxies is the whole product. Report it prominently even though n is small.
- **Calibration plot**: gate_score (x) vs empirical_validity (y), colored by class. A human should be able to eyeball whether the gate is tracking truth or guessing.
- **Per-task breakdown**: where does the gate work, where does it fail. Maps onto the quadrant intuition.
- Bootstrap 95% CIs on rho and AUROC (resample proxies with replacement, >= 1000 iters). With ~40 points the CIs will be wide; that is expected and fine for a go/no-go. Do not over-claim a point estimate.

-----

## 7. Deliverables

Write to `experiments/exp1/`:

- `models.py`, `population.py` (build/label outputs), `proxy_bank.py` (the authored proxies + runner), `gate.py` (holistic + decomposed), `analyze.py` (metrics + plots), `run_exp1.py` (orchestrator), `DESIGN_NOTES.md` (what you found in the repo + deviations).
- `results/exp1_raw.json` — every Output, ProxyResult, GateScore, fully traceable.
- `results/REPORT.md` — the decision. Structure: headline numbers (rho, AUROC, CIs) against the section-0 decision rule; the calibration plot; confounded-class recall; holistic-vs-decomposed and executable-vs-llm_judged comparisons; per-task table; a plain-language verdict (greenlight / kill / ambiguous) and the two or three sentences of why.
- Plots as PNGs in `results/`.

REPORT.md leads with the verdict, not the methodology. I want to read the kill/greenlight call in the first three lines.

-----

## 8. Build order (incremental, testable)

1. DESIGN_NOTES.md from repo inspection. Confirm the gold verifiers actually exist and what they return. **If SQL and schema verifiers do not give a trustworthy gold signal, stop and report that** before building anything else; the experiment is not runnable without a trustworthy gold.
1. Smoke test: 1 task, 5 outputs (1 reference, 2 mutated-wrong, 2 sampled), 2 proxies (1 obviously valid, 1 obviously irrelevant), holistic gate only. Verify the pipeline runs end to end and the obviously-valid proxy gets a higher gate_score than the irrelevant one. If even this inverts, debug before scaling.
1. Scale to 4 tasks, full populations, full proxy banks, both gate variants, voting@3.
1. Analysis + REPORT.md.
1. Cross-family gate (optional) only if time remains and the single-model result is promising.

-----

## 9. Threats to the experiment’s own validity (guard against these)

This experiment has its own construct validity to protect. Watch for:

- **Gold not trustworthy**: if the deterministic verifier itself is wrong (e.g., a SQL check that passes wrong answers), every downstream number is garbage. Spot-check the gold against the reference and a couple of known-wrong mutations by hand before trusting it.
- **Population not spanning the spectrum**: if almost all outputs are correct (or all wrong), MCC is undefined or unstable and AUROC is meaningless. Enforce balance.
- **Leakage into the gate**: the gate must not see gold, population, mutations, or intended_class. Enforce by function signature, not by discipline.
- **Proxy bank authored to flatter the gate**: do not iteratively rewrite proxies after seeing gate scores. Freeze the bank first.
- **Over-reading a thin n**: ~40 points. Report CIs, do not sell a point estimate. A clearly-positive or clearly-null result is trustworthy at this n; a marginal one is not, and “ambiguous” is an honest verdict.
- **The easy-case caveat**: a positive result here means the gate works *where ground truth exists*. It is a necessary, not sufficient, condition for the product. Experiment 2 (adversarial confounded-vs-valid pairs, in genuinely ungrounded domains) is the real test. Say so in the REPORT so we do not over-update on a greenlight.

-----

## 10. Notes for the implementer

- Keep model calls cheap: small populations, voting@3 not @5, 4 tasks not 25. This is a signal experiment, not a benchmark.
- Cache aggressively (gold verdicts and gate scores are deterministic-ish; key by content hash) so re-runs during debugging are free.
- Everything traceable: any number in REPORT.md must be reconstructable from `exp1_raw.json`.
- If you discover the repo already has helpers for any of this (mutation, population sampling, executable verification), use them. Check `acon_trajectory.py`, `test_generator.py`, and `deterministic_verifier.py` first.
