# Experiment 1 — Design Notes & Repo-Inspection Findings

Spec §2 and §8 require inspecting the repo and recording what it actually provides —
plus every deviation forced by reality — before building. This is that record, for the
fresh from-scratch implementation on branch `claude/spec-md-location-l5qlhk`.

## The load-bearing finding: the repo has no executable gold

The spec assumes `rubric_system/deterministic_verifier.py` returns a trustworthy
correct/incorrect signal for SQL and JSON-schema task outputs (SPEC.md §2). It does
not. Verified by direct inspection and an independent adversarial re-check:

- `DeterministicVerifier` (line 278) has one public method,
  `verify_criterion(criterion, content) -> Optional[CriterionScore]` (lines 306-340).
  It scores rubric **criteria** against generated prose, via 13 surface checkers:
  word/char/item counts (377-514), markdown structure presence (555-637),
  Python **syntax** via `ast.parse` (line 534 — parses, never executes),
  bash-safety regexes (639-686), and section presence (721-755).
- EVAL.md Run 11 "Fix 7: Deterministic bash/SQL verifiers" resolves to:
  `_check_sql_patterns` (688-719), whose only check is the
  `_SQL_SELECT_STAR` regex (line 150) — a style penalty; and `_check_bash_safety`.
- **No SQL execution anywhere**: the module imports only `ast`, `re`,
  `typing.Optional`, and `rubric_system.models` (lines 16-20). The repo-wide
  `sqlite3` hits (`rubric_harness.py:9284`, `reference_pairs.py`,
  `rubric_learning.py`, `metrics_dashboard.py`) are the harness's own telemetry
  store — no code path executes SQL *produced by a task output* against data.
- **No `jsonschema` import anywhere** in the repo; no JSON-instance validation of
  any kind; no `.db`/`.sqlite`/fixture files exist (repo-wide find: zero).
- The named tasks exist only as one-sentence prompts in
  `rubric_system/sample_rubrics.py` (`sql_ltv_query` line 381, `billing_schema`
  line 559, `csv_parser` line 193) plus LLM-rubric-scored outputs in
  `eval_run*_artifacts/` and `eval_results_run*.json` — best-of-N artifacts scoring
  56-80% on their own rubrics, never executed or validated. The repo's
  `output_sql_ltv_query.md` files are T-SQL (run10) / PostgreSQL (run8) dialect and
  not SQLite-executable as-is.

**Conclusion:** the repo's verifier cannot serve as Exp-1's gold. Per §8's
stop-condition this is reported here (and was reported in the earlier implementation
round, where the same conclusion was reached and building a self-contained gold was
approved). This implementation builds a **self-contained executable gold**.

## Deviations from the spec (each forced by the findings above)

1. **Gold is built in-experiment, not reused from the repo** (§2 assumption false).
   - `gold/sql_gold.py`: a deterministically seeded in-memory SQLite DB (fixed seed,
     integer-cents amounts so comparisons are exact, distinct LTVs so the top-10
     ranking is unambiguous, two zero-payment customers so join-type choices are
     observable) + a pinned reference query per task whose executed result set *is*
     the truth. `gold_verdict` extracts the candidate's ```sql block, executes it,
     and compares result tables (ordered comparison — the prompts pin column order
     and ordering).
   - `gold/schema_gold.py`: a pinned reference JSON Schema (draft 2020-12) + a
     battery of held-out labeled instances. `gold_verdict` = the candidate schema is
     itself valid AND accepts every valid instance AND rejects every invalid one
     (via `jsonschema.Draft202012Validator`). Every breaking mutation is covered by
     at least one battery instance (asserted in tests).
   - `gold/csv_gold.py`: a pinned parsing contract + fixed messy-CSV fixtures with
     expected parses. `gold_verdict` executes the candidate's ```python block in a
     subprocess (timeout, isolated) against the fixtures and compares exact output.

2. **Task prompts are pinned.** The repo prompts are one sentence and underdetermined
   ("from a schema you define"; header semantics for csv unpinnable), so no fixed
   gold can apply unmodified. Exp-1 prompt variants pin the schema/DDL, required
   output columns and ordering (SQL), the entity contract (schema task), and the
   function signature + parsing rules (csv). The tasks are otherwise faithful to the
   originals. Task IDs: `sql_ltv_top10`, `sql_revenue_by_tier`, `billing_schema`,
   `csv_parser`.

3. **Task selection** (§3): the spec's recommended slots 1-3 are kept —
   `sql_ltv_query` (pinned as `sql_ltv_top10`), `billing_schema`, `csv_parser`
   (kept, unlike the earlier round: its gold is cheap Python subprocess execution).
   Slot 4: `api_rate_limiter` needs Redis and `rust_concurrent_cache` needs a Rust
   toolchain — both excluded by the spec's own cost guidance — so a **second SQL
   variant** (`sql_revenue_by_tier`) substitutes, exactly as §3 item 4 directs.
   Families: SQL x2, JSON-schema x1, code x1.

4. **`sampled` outputs are pre-authored stand-ins in offline mode.** True sampled
   outputs require model calls, and pre-existing repo outputs answer the *unpinned*
   prompts (wrong dialect / wrong contract), so they cannot be graded fairly by the
   pinned gold. Offline, each task carries hand-authored full outputs of varied
   quality and surface form, labeled `origin=sampled` with
   `gold_meta.provenance="pre-authored stand-in"`. With an API key,
   `population.py --sample` generates real samples at varied temperature and they
   replace/augment the stand-ins. This is recorded so nobody mistakes offline
   stand-ins for true model samples.

5. **Gold and proxy bank share no helpers.** `proxy_bank.py` re-implements its own
   SQL substrate (different seed and data generator), its own schema-instance
   battery, and its own csv fixtures. Valid executable proxies therefore reach
   correctness conclusions independently of the gold; a test asserts `proxy_bank`
   never imports from `gold/`.

6. **Mock gate for offline runnability.** `ANTHROPIC_API_KEY` is not set in this
   environment (and cannot be added to a running session), so `gate.py --mock`
   produces deterministic scores derived **only** from the two allowed inputs
   (task prompt + proxy definition) via a fixed keyword heuristic + content-hash
   jitter. This validates the full pipeline (gold, populations, MCC, bootstrap,
   plots, report) offline. A mock run's REPORT.md is stamped
   **MOCK — pipeline validation only, not an experimental verdict**. `llm_judged`
   proxies likewise carry a deterministic `mock_predicate` used only offline; a
   keyed run judges each output from the proxy's judge prompt via the model.

## What was reused from the repo (and what was not)

- **Spec §2 said reuse `scoring_engine.py`'s model-call plumbing — inspection shows
  it has none** (no `anthropic` import; `DocumentScorer` takes an injected client,
  line 484). The real plumbing lives in `rubric_harness.py` / `eval_harness.py`, and
  it is idioms, not importable functions (the cleanest helper, `_call_claude`, is a
  private method on the ~9500-line `RubricLoop`). So `gate.py` copies the repo
  idioms rather than importing:
  - client: `anthropic.Anthropic(timeout=httpx.Timeout(600.0, connect=30.0))`
    (cf. `rubric_harness.py:81`, `eval_harness.py:712`);
  - default model `claude-sonnet-4-20250514` (the repo-wide default, ~14 sites;
    overridable via `--model`);
  - API-key fallback env → `<exp dir>/.env` → `~/.anthropic/api_key`
    (mirrors `rubric_harness.py:100-111`);
  - JSON extraction: code-fence → `json.loads` → brace-regex fallback
    (mirrors `RubricLoop._extract_json`, `rubric_harness.py:7313-7325`).
- **Spec §1 said reuse enums/types from `rubric_system/models.py` — none apply.**
  Full inventory (3 enums, 15 dataclasses) checked: `ScoringMethod`/`CriterionTier`
  classify rubric-criteria math, `PairSource` (caller|store|self_contrast|synthetic)
  is pair provenance, not output origin; no counterpart exists for
  GroundedTask/Output/ProxyCheck/ProxyResult/GateScore. Exp-1's `models.py` defines
  fresh `Origin`/`ProxyKind`/`IntendedClass` enums and the five dataclasses. Two
  conventions are adopted: the `task_hash = sha256(task)[:8]` keying used by
  `ReferencePair`/`ScoredRubricRecord`, and call-site `dataclasses.asdict`
  serialization (with explicit Enum→value conversion, which the repo lacks).
- `deterministic_verifier.py`'s surface checks were mined as **inspiration for
  confounded/irrelevant proxies** (its `SELECT *` regex and markdown-structure
  checks are exactly the class of check Exp-1 must show the gate can flag), but no
  code is imported.

## Integrity enforcement (spec §5, §9)

- Gate entry points take **exactly** `(task_prompt, proxy_definition)` plus
  keyword-only config (`variant`, `model`, `votes`, `cache_dir`, `mock`). They
  cannot receive the population, gold verdicts, mutations, or `intended_class`.
  `tests/test_exp1.py::test_gate_signature_leakage_guard` asserts the signature.
- `intended_class` is used only for stratified analysis and plot coloring;
  `empirical_validity` is purely MCC of proxy verdicts vs gold verdicts.
- The proxy bank is frozen before any gate run (authored against task spec +
  reference output only, never against per-output gold verdicts or gate scores).
- Gold trustworthiness is spot-checked in tests: the reference output passes, every
  correctness-breaking mutation fails, every surface-only mutation still passes.
- Population balance is enforced: per-task pass rate must land in [0.25, 0.75] or
  the run aborts with a report.

## How to run

Offline (deterministic, no key — validates everything except the real gate):

```
python -m experiments.exp1.run_exp1 --smoke --mock    # 1 task, 5 outputs, 2 proxies
python -m experiments.exp1.run_exp1 --mock            # full 4-task pipeline
python -m experiments.exp1.tests.test_exp1            # guard + unit tests
```

Real verdict (needs a key; add `ANTHROPIC_API_KEY` to the environment at
claude.ai/code — applies to new sessions — or drop it in `experiments/exp1/.env`):

```
pip install -r experiments/exp1/requirements-exp1.txt
python -m experiments.exp1.run_exp1 --tasks all --gate both
```

Outputs land in `experiments/exp1/results/`: `REPORT.md` (verdict first),
`exp1_raw.json` (every Output/ProxyResult/GateScore, fully traceable), and
`calibration_{holistic,decomposed}.png`. Gate calls are cached by content hash under
`results/.cache/` so re-runs during debugging are free.

## Adversarial review outcomes (post-implementation hardening)

A multi-agent adversarial review of the implementation surfaced 17 candidate
defects; each was reproduced or refuted, and the real ones fixed:

- **Critical**: the billing_schema judge prompt contains literal braces, and
  `str.format` rendering crashed every keyed run with `KeyError: 'unit'` —
  invisible offline because mock predicates bypass rendering. Judge prompts
  are now rendered by literal `{output}` substitution
  (`gate.render_judge_prompt`), regression-tested over the whole bank.
- **Gold hardening**: the schema battery had uncovered contract clauses
  (a schema relaxing e.g. `status` required or price integer-ness still
  passed); the battery now covers every clause in both directions
  (33 instances, per-clause coverage test). The SQL semicolon pre-check
  false-rejected legal queries with `;` in comments/strings (SQLite itself
  enforces single-statement; check removed). Extractors preferred the *last*
  code block, so trailing example/DDL-echo blocks shadowed the real
  schema/query/code — extraction is now content-aware (schema-shaped block,
  `def parse_csv` block, SELECT/WITH block; ```sqlite and one-line fences
  accepted). The csv runner executed candidates as `__main__` (demo blocks
  ran, stdout writes corrupted the protocol); candidates are now imported as
  a module with file-based IO.
- **Discipline**: one llm_judged mock predicate keyed on an alias (`c2`)
  specific to a population stand-in — an authoring-independence violation;
  replaced with a contract-derived fan-out heuristic. Note the general
  caveat: mock predicates are deterministic stand-ins; their empirical
  validity in mock runs says nothing about real LLM judges.
- **Analysis honesty**: constant gate scores / single-class labels now yield
  an INVALID verdict ("statistics undefined — run is broken") instead of a
  sentinel-driven KILL; bootstrap CIs that skipped degenerate resamples say
  so in the report. The gate cache key now includes a fingerprint of the
  gate's prompts/heuristics, so editing gate code invalidates stale caches.
- Assorted: duplicate sampled texts no longer collide on `output_id`;
  `--sample` is rejected under `--mock`/`--smoke` instead of silently
  dropped; empty `--tasks` fails fast; the smoke path no longer builds the
  population twice.

## Known properties / honest caveats

- ~40 (task, proxy) pairs and ~25 outputs per task: thin by design (spec §10);
  every headline metric carries bootstrap 95% CIs and REPORT.md refuses to sell a
  point estimate (§9).
- Two SQL "valid" proxies are deliberately weaker than the gold (independent, smaller
  substrate), giving the gate something nuanced to predict rather than a bimodal
  bank.
- A positive result is the **easy case** (ground truth exists): necessary, not
  sufficient. Experiment 2 (adversarial confounded-vs-valid pairs in ungrounded
  domains) is the real test. REPORT.md says this in the verdict section.
