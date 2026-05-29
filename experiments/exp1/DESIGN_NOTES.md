# Experiment 1 — Design Notes & Repo-Inspection Findings

What the repo actually provides, the deviations this forced, and how to run the
experiment. (Spec §2 + §8 require recording this before building.)

## The load-bearing finding: the repo has no execute-and-compare gold

The spec assumed `rubric_system/deterministic_verifier.py` returns a trustworthy
correct/incorrect signal for SQL and JSON-schema tasks. It does **not**. That module
(`DeterministicVerifier`, line 278) scores rubric **Criteria**, not task outputs, via
**pattern matching**:

- `verify_criterion(criterion, content)` runs a chain of regex/`ast` checkers
  (lines 306-340): word/char/item counts, header/bullet/table presence, Python
  *syntax* (`ast.parse`, line 516 — compiles, does not execute), section presence.
- The "Fix 7: Deterministic bash/SQL verifiers" from EVAL.md Run 11 is:
  - `_check_sql_patterns` (line 688) — a regex that only penalizes `SELECT *`.
  - `_check_bash_safety` (line 639) — a regex for dangerous shell commands.
- **No SQL execution, no seeded DB** (`find . -name '*.db'/'*.sqlite'` → none),
  **no `jsonschema`** (never imported), **no held-out instances**.

The named tasks (`sql_ltv_query`, `billing_schema`, `csv_parser`, …) exist only as
*prompts + generated outputs + LLM-judged rubrics* in `sample_rubrics.py` and
`eval_run8_artifacts/` (e.g. `output_sql_ltv_query.md`, `output_billing_schema.md`).
No executable ground truth is attached to any of them.

**Conclusion:** the repo's verifier cannot serve as Exp-1's gold. Per the spec's §8
stop-condition we reported this, and (per user decision) built a **self-contained
executable gold** instead.

## Deviations from the spec (all intentional, user-approved)

1. **Gold is built in-experiment, not reused from the repo.**
   - `gold/sql_gold.py`: a deterministically-seeded in-memory SQLite DB (`build_db`,
     fixed seed `1729`, distinct LTV values so the top-10 ranking is unambiguous) +
     a pinned **reference query** per task whose executed result set *is* the truth.
     `gold_verdict` extracts the candidate's SQL, executes it, and compares result
     tables (ordered for rankings, set-compared for groupings).
   - `gold/schema_gold.py`: a pinned **reference schema** + a battery of held-out
     labeled instances per task. `gold_verdict` = the candidate schema accepts every
     valid instance and rejects every invalid one (via `jsonschema.Draft202012Validator`).

2. **Tasks: SQL + JSON-schema only (CSV dropped), 4 tasks across the two families**
   to reach ~34 (task,proxy) pairs: `sql_ltv_top10`, `sql_revenue_by_tier`,
   `billing_schema`, `event_schema`.

3. **`sql_ltv_query` prompt pinned.** The original ("from a schema you define") is too
   open for a deterministic gold, so we pin a concrete schema + seeded data and adjust
   the prompt text. The task is otherwise faithful (top-10 by LTV excluding refunds).

4. **Gold and proxy bank authored independently, with NO shared helpers**
   (user instruction + spec author-discipline). `proxy_bank.py` re-implements its own
   SQL execution substrate (`_proxy_db`, different seed `424242`) and its own
   `jsonschema` instance battery. The valid executable proxies therefore *independently*
   reach the same correctness conclusion as the gold without importing it.

5. **Mock gate for offline runnability.** `ANTHROPIC_API_KEY` is unset in this
   environment and `anthropic` was not installed. `gate.py --mock` returns deterministic
   pseudo-scores derived **only** from the two allowed strings (task prompt + proxy
   definition), so the whole pipeline (gold, populations, MCC, bootstrap, plots) runs
   and is validated offline. The real ρ/AUROC verdict requires a key (see below).
   `llm_judged` proxies likewise carry a `mock_predicate` used only offline; a keyed run
   judges each output from the proxy's prompt via the model.

## Reused repo patterns (not coupled to repo internals)

- Anthropic client construction: `anthropic.Anthropic(timeout=httpx.Timeout(600.0,
  connect=30.0))` and default model `claude-sonnet-4-20250514`
  (cf. `eval_harness.py:712`, `rubric_system/scoring_engine.py:554`).
- API-key fallback loader mirrors `rubric_harness.py:103-110` (env → `.env` →
  `~/.anthropic/api_key`); see `gate.load_api_key`.
- `rubric_system/models.py` enums (`ScoringMethod`, `CriterionTier`) describe rubric
  *criteria*, not proxy/gold concepts, so nothing there was reusable for Exp-1's data
  model; `models.py` defines fresh `Origin`/`ProxyKind`/`IntendedClass` enums.

## Integrity enforcement (spec §5, §9)

- The gate functions' signatures are `(task_prompt, proxy_definition, *, ...)` — they
  **cannot** receive gold verdicts, the population, mutations, or `intended_class`.
  `tests/test_exp1.py::test_gate_signature_leakage_guard` asserts this.
- `intended_class` is used only for stratified analysis and plot coloring, never to
  compute `empirical_validity` (which is purely MCC of proxy-verdicts vs gold).
- Proxy bank is frozen before any gate run; not rewritten after seeing gate scores.

## How to run

Offline (deterministic, no key — validates everything except the real gate judgment):
```
python -m experiments.exp1.run_exp1 --smoke --mock     # tiny pipeline check
python -m experiments.exp1.run_exp1 --mock             # full 4-task pipeline
python -m experiments.exp1.tests.test_exp1             # guard tests
```

Real verdict (needs a key + the analysis deps):
```
pip install -r experiments/exp1/requirements-exp1.txt
export ANTHROPIC_API_KEY=...          # or create experiments/exp1/.env
python -m experiments.exp1.run_exp1 --tasks all --gate both
```
Outputs land in `experiments/exp1/results/`: `REPORT.md` (verdict first), `exp1_raw.json`
(fully traceable), and `calibration_{holistic,decomposed}.png`. Gate calls are cached by
content hash (`results/.cache/`) so re-runs during debugging are free.

## Known properties / honest caveats

- Schema *valid* proxies score MCC ≈ 0.6 (not 1.0) because the proxy bank's independent
  instance battery is smaller than the gold's and misses a few mutations — a realistic
  "weaker but valid" check, which gives the gate something nuanced to predict.
- Populations are ~16-18 outputs/task (small by design, spec §10). The thin n is in the
  ~34 proxy pairs; that is why every headline metric is reported with bootstrap 95% CIs.
- A positive result is the **easy case** (ground truth exists). Necessary, not
  sufficient — Experiment 2 (ungrounded adversarial pairs) is the real test.
