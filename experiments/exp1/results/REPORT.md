> **MOCK RUN — pipeline validation only.** The gate scores below come from the deterministic offline mock, not a model. This is NOT an experimental verdict; run with an API key for the real one.

# Experiment 1 verdict: AMBIGUOUS

**rho=0.459 (CI lower 0.153), AUROC=0.924 (CI lower 0.798): between kill and greenlight, or CIs cross the kill thresholds. Proceed to Experiment 2 with tempered expectations.**

Primary variant: decomposed gate — rho **+0.459** (95% CI [+0.153, +0.703]), AUROC **0.924** (95% CI [0.798, 1.000]), n=41.
Decision rule (SPEC.md section 0): greenlight iff rho >= 0.5 AND AUROC >= 0.75 with CIs excluding the kill thresholds (rho <= 0.2, AUROC <= 0.6).

## Headline numbers

| gate variant | Spearman rho [95% CI] | AUROC [95% CI] | confounded-class recall | mean vote variance |
|---|---|---|---|---|
| holistic | +0.491 [+0.176, +0.715] | 0.917 [0.780, 1.000] | 0.65 (n=20) | 0.0004 |
| decomposed | +0.459 [+0.153, +0.703] | 0.924 [0.798, 1.000] | 0.65 (n=20) | 0.0002 |

**Confounded-class recall** — of proxies the author labeled confounded whose empirical validity came out low, the fraction the gate scored below 0.5. Catching confounded proxies is the whole product; this is the single most important diagnostic (small n, read with care).

## Calibration

![calibration holistic](calibration_holistic.png)
![calibration decomposed](calibration_decomposed.png)

A gate that tracks truth shows an upward trend; a guessing gate is a cloud. Orange (confounded) points in the lower-right quadrant are gate failures on the crux cases.

## Executable vs llm_judged proxies

**holistic:**
- executable: rho **+0.401** (95% CI [+0.013, +0.670]), AUROC **1.000** (95% CI [1.000, 1.000]), n=33
- llm_judged: rho **+0.810** (95% CI [+0.263, +1.000]), AUROC **0.800** (95% CI [0.333, 1.000]), n=8

**decomposed:**
- executable: rho **+0.352** (95% CI [-0.046, +0.642]), AUROC **1.000** (95% CI [1.000, 1.000]), n=33
- llm_judged: rho **+0.690** (95% CI [-0.062, +1.000]), AUROC **0.800** (95% CI [0.333, 1.000]), n=8

## Per-task breakdown

**holistic:**

| task | rho | AUROC | n |
|---|---|---|---|
| billing_schema | +0.710 | 1.000 | 10 |
| csv_parser | +0.420 | 1.000 | 10 |
| sql_ltv_top10 | +0.575 | 0.917 | 11 |
| sql_revenue_by_tier | +0.483 | 0.875 | 10 |

**decomposed:**

| task | rho | AUROC | n |
|---|---|---|---|
| billing_schema | +0.624 | 1.000 | 10 |
| csv_parser | +0.459 | 1.000 | 10 |
| sql_ltv_top10 | +0.543 | 0.917 | 11 |
| sql_revenue_by_tier | +0.502 | 0.875 | 10 |

## Population balance (spec section 3)

| task | outputs | gold pass | gold fail | pass rate |
|---|---|---|---|---|
| sql_ltv_top10 | 20 | 8 | 12 | 0.4 |
| sql_revenue_by_tier | 16 | 7 | 9 | 0.438 |
| billing_schema | 17 | 6 | 11 | 0.353 |
| csv_parser | 14 | 6 | 8 | 0.429 |

## Per-proxy detail

| proxy | class | kind | empirical validity (MCC) | gate holistic | gate decomposed |
|---|---|---|---|---|---|
| billing_schema::llm_contract_check | valid | llm_judged | +0.62 | 0.83 | 0.81 |
| billing_schema::battery_accepts_rejects | valid | executable | +0.55 | 0.98 | 0.94 |
| billing_schema::seats_integer_min1 | confounded | executable | +0.34 | 0.42 | 0.46 |
| billing_schema::additional_props_false | confounded | executable | +0.27 | 0.48 | 0.44 |
| billing_schema::has_annotations | irrelevant | executable | +0.27 | 0.02 | 0.02 |
| billing_schema::required_has_tenant | confounded | executable | +0.18 | 0.29 | 0.27 |
| billing_schema::status_enum_exact | confounded | executable | +0.18 | 0.42 | 0.46 |
| billing_schema::llm_professional | irrelevant | llm_judged | +0.02 | 0.16 | 0.15 |
| billing_schema::parses_as_schema | confounded | executable | +0.00 | 0.25 | 0.27 |
| billing_schema::nesting_depth | irrelevant | executable | +0.00 | 0.16 | 0.15 |
| csv_parser::own_fixtures_pass | valid | executable | +0.65 | 0.93 | 0.95 |
| csv_parser::llm_contract_correct | valid | llm_judged | +0.45 | 0.86 | 0.83 |
| csv_parser::text_handles_quotes | confounded | executable | +0.35 | 0.25 | 0.26 |
| csv_parser::llm_code_quality | irrelevant | llm_judged | +0.23 | 0.14 | 0.14 |
| csv_parser::simple_case_correct | confounded | executable | +0.00 | 0.57 | 0.59 |
| csv_parser::runs_on_quoted_input | confounded | executable | +0.00 | 0.54 | 0.58 |
| csv_parser::defines_and_runs | confounded | executable | +0.00 | 0.57 | 0.58 |
| csv_parser::text_strips_fields | confounded | executable | +0.00 | 0.26 | 0.27 |
| csv_parser::has_type_hints | irrelevant | executable | +0.00 | 0.16 | 0.13 |
| csv_parser::under_60_lines | irrelevant | executable | -0.45 | 0.18 | 0.16 |
| sql_ltv_top10::exec_matches_ref | valid | executable | +1.00 | 0.92 | 0.96 |
| sql_ltv_top10::exec_top_row_matches | valid | executable | +0.82 | 0.95 | 0.94 |
| sql_ltv_top10::llm_ltv_semantics | valid | llm_judged | +0.53 | 0.41 | 0.45 |
| sql_ltv_top10::text_order_desc_limit10 | confounded | executable | +0.34 | 0.29 | 0.30 |
| sql_ltv_top10::text_uses_cte | irrelevant | executable | +0.28 | 0.13 | 0.14 |
| sql_ltv_top10::text_mentions_refund | confounded | executable | +0.27 | 0.26 | 0.26 |
| sql_ltv_top10::exec_returns_10_rows | confounded | executable | +0.19 | 0.56 | 0.56 |
| sql_ltv_top10::exec_no_error | confounded | executable | +0.00 | 0.60 | 0.59 |
| sql_ltv_top10::text_under_20_lines | irrelevant | executable | +0.00 | 0.18 | 0.16 |
| sql_ltv_top10::text_has_group_by | confounded | executable | -0.28 | 0.25 | 0.29 |
| sql_ltv_top10::llm_readability | irrelevant | llm_judged | -0.28 | 0.13 | 0.15 |
| sql_revenue_by_tier::exec_matches_ref | valid | executable | +1.00 | 0.96 | 0.94 |
| sql_revenue_by_tier::llm_net_revenue_semantics | valid | llm_judged | +0.59 | 0.47 | 0.46 |
| sql_revenue_by_tier::text_order_desc | confounded | executable | +0.33 | 0.28 | 0.26 |
| sql_revenue_by_tier::exec_returns_3_rows | confounded | executable | +0.23 | 0.58 | 0.57 |
| sql_revenue_by_tier::text_mentions_refund | confounded | executable | +0.23 | 0.29 | 0.25 |
| sql_revenue_by_tier::exec_no_error | confounded | executable | +0.00 | 0.56 | 0.55 |
| sql_revenue_by_tier::text_under_15_lines | irrelevant | executable | +0.00 | 0.13 | 0.14 |
| sql_revenue_by_tier::text_uppercase_keywords | irrelevant | executable | +0.00 | 0.14 | 0.14 |
| sql_revenue_by_tier::llm_readability | irrelevant | llm_judged | +0.00 | 0.12 | 0.15 |
| sql_revenue_by_tier::text_group_by_tier | confounded | executable | -0.05 | 0.44 | 0.45 |

## Caveats (spec section 9)

- Thin n (41 proxy datapoints): CIs are wide by design; do not over-read the point estimates. A clearly-positive or clearly-null result is trustworthy at this n; a marginal one is not.
- **Easy-case caveat**: a positive result means the gate works where ground truth exists. Necessary, not sufficient — Experiment 2 (adversarial confounded-vs-valid pairs in genuinely ungrounded domains) is the real test. Do not over-update on a greenlight.
- Gold trustworthiness was spot-checked in code: reference outputs pass, every breaking mutation fails, every surface mutation passes (tests/test_exp1.py).
- This was a MOCK run: gate scores are a deterministic keyword heuristic, present only to validate the pipeline end to end.

Config: {"generated_at": "2026-07-19T02:19:17.900715+00:00", "mock": true, "smoke": false, "gate_model": "mock", "votes": 3, "variants": ["holistic", "decomposed"], "task_ids": ["sql_ltv_top10", "sql_revenue_by_tier", "billing_schema", "csv_parser"], "sampled_per_task": 0}

Every number above is reconstructable from `exp1_raw.json`.