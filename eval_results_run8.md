# Eval Results: Rubric Harness vs. Vanilla Claude

**Generated:** 2026-03-31 05:10:31 UTC  
**Model:** `claude-sonnet-4-20250514`  
**Max harness iterations:** 0

## Per-Task Results

| Task | Domain | Baseline % | Harness % | Delta | Iters | Base Time | Harness Time |
|------|--------|:----------:|:---------:|:-----:|:-----:|:---------:|:------------:|
| cold_outreach_email | cold_outreach_email | 46.9% | 79.5% | +32.6% | 4 | 64s | 276s |
| csv_parser | code_generation | 38.0% | 61.4% | +23.3% | 3 | 97s | 358s |
| exec_summary | summarization | 26.3% | 58.0% | +31.7% | 4 | 37s | 263s |
| sql_ltv_query | sql_query | 50.1% | 62.5% | +12.4% | 4 | 59s | 477s |
| agi_counterargument | argumentation | 35.0% | 61.1% | +26.1% | 3 | 55s | 318s |
| billing_schema | schema_design | 21.1% | 56.1% | +35.0% | 4 | 86s | 588s |
| attention_explanation | explanation | 64.1% | 73.6% | +9.4% | 7 | 70s | 750s |
| startup_naming | creative_naming | 43.8% | 64.6% | +20.8% | 6 | 52s | 676s |
| bash_backup | bash_scripting | 52.0% | 55.2% | +3.2% | 3 | 103s | 389s |
| investment_memo | investment_memo | 66.5% | 78.0% | +11.5% | 3 | 74s | 344s |

## Aggregate Statistics

| Metric | Value |
|--------|-------|
| Tasks evaluated | 10 |
| Mean lift | **+20.6%** |
| Median lift | +22.1% |
| Std dev | 11.0% |
| Improved (>1%) | 10/10 |
| Neutral (±1%) | 0/10 |
| Regressed (<-1%) | 0/10 |

## Per-Criterion Lift (top 15 by avg lift across tasks)

| Criterion | Category | Avg Lift | Appearances |
|-----------|----------|:--------:|:-----------:|
| schema_correctness | quality | +75.0% | 1 |
| schema_completeness | design | +75.0% | 1 |
| arg_steelman | intellectual_honesty | +70.0% | 1 |
| sum_exec_value | utility | +67.5% | 1 |
| schema_extensibility | architecture | +60.0% | 1 |
| sum_fidelity | accuracy | +57.5% | 1 |
| code_robustness | reliability | +56.2% | 1 |
| name_variety | range | +50.0% | 1 |
| email_subject | engagement | +47.5% | 1 |
| email_value_prop | persuasion | +38.7% | 1 |
| email_length | structure | +38.6% | 1 |
| email_opening | engagement | +37.5% | 1 |
| code_api_design | usability | +33.7% | 1 |
| expl_accuracy | correctness | +33.7% | 1 |
| memo_thesis | conviction | +32.5% | 1 |

## Cost & Token Comparison

| Metric | Baseline | Harness |
|--------|----------|---------|
| Tasks with data | 10 | 10 |
| Total wall time | 698s | 4439s |
| Avg time / task | 70s | 444s |
| Input tokens (total) | 270 | ~328,000 (est.) |
| Output tokens (total) | 15,012 | ~61,500 (est.) |
| Est. cost (USD) | $0.2260 | ~$1.9065 (est.) |
| Avg iterations | 1 | 4.1 |

> Harness token/cost figures are estimates based on 8,000 input + 1,500 output tokens per iteration. Actual usage varies.