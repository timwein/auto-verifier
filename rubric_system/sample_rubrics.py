#!/usr/bin/env python3
"""
Sample Rubrics — 10 task-specific rubrics demonstrating the scoring system's range.

Each rubric uses the canonical v4 models and scoring methods to evaluate
diverse output types: emails, code, summaries, SQL, arguments, schemas,
explanations, naming, scripts, and investment memos.

Usage:
    from rubric_system.sample_rubrics import ALL_SAMPLE_RUBRICS, build_rubric_for_task
    rubric = build_rubric_for_task(1)  # Cold outreach email
    rubric = ALL_SAMPLE_RUBRICS[0]()   # Same thing
"""

try:
    from rubric_system.models import (
        ScoringMethod, SubAttribute, ScoringRubric, Criterion, Rubric,
    )
except ImportError:
    from models import (
        ScoringMethod, SubAttribute, ScoringRubric, Criterion, Rubric,
    )


# ============================================================================
# Reusable scoring rubric factories (task-agnostic)
# ============================================================================

def _weighted(max_pts: int, subs: list[tuple[str, str, float, str]]) -> ScoringRubric:
    """Shorthand for WEIGHTED_COMPONENTS rubric."""
    return ScoringRubric(
        method=ScoringMethod.WEIGHTED_COMPONENTS,
        max_points=max_pts,
        sub_attributes=[
            SubAttribute(sub_id=s[0], description=s[1], weight=s[2], measurement=s[3])
            for s in subs
        ],
    )


def _penalty(max_pts: int, penalties: dict[str, float]) -> ScoringRubric:
    """Shorthand for PENALTY_BASED rubric."""
    return ScoringRubric(
        method=ScoringMethod.PENALTY_BASED,
        max_points=max_pts,
        penalties=penalties,
    )


def _binary(max_pts: int = 3) -> ScoringRubric:
    """Shorthand for BINARY rubric."""
    return ScoringRubric(method=ScoringMethod.BINARY, max_points=max_pts)


# ============================================================================
# Task 1: Cold Outreach Email to Series A Founder
# ============================================================================

def build_cold_outreach_email_rubric() -> Rubric:
    task = "Write a cold outreach email to a Series A founder pitching angel investment"

    criteria = [
        Criterion(
            id="email_subject",
            category="engagement",
            description="Subject line is compelling and specific — not generic or spammy",
            pass_condition="Subject is <60 chars, references something specific to the recipient, "
                          "creates curiosity without clickbait. No 'Quick question' or 'Touching base'.",
            scoring=_weighted(10, [
                ("specificity", "References recipient's company/round/domain", 0.40,
                 "1.0 if names company or specific context, 0.0 if generic"),
                ("brevity", "Under 60 chars, scannable on mobile", 0.25,
                 "1.0 if ≤60 chars, 0.5 if ≤80, 0.0 if >80"),
                ("curiosity_hook", "Creates reason to open without being clickbait", 0.35,
                 "1.0 if compelling + honest, 0.5 if generic, 0.0 if spammy"),
            ]),
            pass_examples=["'$2M angel check for Acme's Series A — operator background in logistics'"],
            fail_examples=["'Quick question'", "'Exciting investment opportunity!'"],
        ),
        Criterion(
            id="email_opening",
            category="engagement",
            description="First sentence earns the right to the second — no throat-clearing",
            pass_condition="Opens with specific signal: why now, why them, what you noticed. "
                          "No 'I hope this finds you well' or self-introductions.",
            scoring=_penalty(8, {
                "generic_greeting": -3.0,
                "self_intro_first": -2.0,
                "no_specific_signal": -2.0,
                "too_long_opening": -1.5,
            }),
            pass_examples=["'Saw your Techcrunch piece on [X] — the way you're attacking [problem] maps to what I built at [company]'"],
            fail_examples=["'Hi, my name is Tim and I'm an angel investor...'"],
        ),
        Criterion(
            id="email_value_prop",
            category="persuasion",
            description="Clearly articulates what the angel brings beyond capital",
            pass_condition="Specific operational value: domain expertise, network, customer intros, "
                          "hiring help. Concrete, not vague ('I can help').",
            scoring=_weighted(10, [
                ("specificity", "Names concrete value (intros, expertise, past wins)", 0.45,
                 "1.0 if 2+ specific offerings, 0.5 if 1 vague, 0.0 if just capital"),
                ("relevance", "Value prop maps to recipient's actual needs/stage", 0.35,
                 "1.0 if clearly relevant to their domain/stage, 0.0 if generic"),
                ("credibility", "Claims are verifiable (named companies, outcomes)", 0.20,
                 "1.0 if verifiable claims, 0.5 if plausible, 0.0 if unsubstantiated"),
            ]),
            pass_examples=["'I scaled logistics ops from $5M to $80M ARR at ShipCo — happy to open my network of 20+ VP Supply Chain contacts'"],
            fail_examples=["'I bring smart capital and strategic value to my portfolio companies'"],
        ),
        Criterion(
            id="email_social_proof",
            category="credibility",
            description="Establishes credibility without bragging",
            pass_condition="1-2 relevant proof points: portfolio wins, operating background, "
                          "mutual connections. Woven in, not a resume dump.",
            scoring=_weighted(8, [
                ("proof_quality", "Proof points are relevant and impressive", 0.50,
                 "1.0 if directly relevant wins, 0.5 if tangential, 0.0 if absent"),
                ("restraint", "1-2 points, not a resume dump", 0.30,
                 "1.0 if 1-2 tight proof points, 0.5 if 3-4, 0.0 if resume paragraph"),
                ("natural_integration", "Proof woven into narrative, not listed", 0.20,
                 "1.0 if organic, 0.0 if bullet-pointed credentials"),
            ]),
            pass_examples=["'...when I was CTO at [X] (acq. by Google), we solved a similar cold-start problem'"],
            fail_examples=["'I have 15 years of experience, 30 investments, board seats at...'"],
        ),
        Criterion(
            id="email_cta",
            category="conversion",
            description="Call to action is low-friction and specific",
            pass_condition="Single, clear ask. Low commitment (15-min call, not 'let's meet'). "
                          "Suggests specific times or next step.",
            scoring=_weighted(8, [
                ("clarity", "Single unambiguous ask", 0.35,
                 "1.0 if one clear ask, 0.5 if implied, 0.0 if multiple/confusing"),
                ("low_friction", "Minimal commitment required", 0.35,
                 "1.0 if 15-min call or async, 0.5 if meeting, 0.0 if big ask"),
                ("specificity", "Includes proposed time or concrete next step", 0.30,
                 "1.0 if specific availability, 0.5 if 'sometime this week', 0.0 if open-ended"),
            ]),
            pass_examples=["'Free for a 15-min call Thursday or Friday afternoon? Happy to share my thesis on [space] first over email if you prefer.'"],
            fail_examples=["'Let me know if you're interested in chatting sometime.'"],
        ),
        Criterion(
            id="email_tone",
            category="voice",
            description="Tone is peer-to-peer, confident but not presumptuous",
            pass_condition="Reads like one founder talking to another. Not sycophantic, not salesy, "
                          "not formal. Respects their time.",
            scoring=_penalty(6, {
                "sycophantic_language": -2.0,
                "salesy_pressure": -2.0,
                "overly_formal": -1.5,
                "presumptuous_familiarity": -1.5,
                "humble_brag": -1.0,
            }),
            pass_examples=["Direct, warm, brief — reads like a text from a smart friend"],
            fail_examples=["'I'd be truly honored to be part of your incredible journey'"],
        ),
        Criterion(
            id="email_length",
            category="structure",
            description="Email is scannable in <30 seconds — under 150 words",
            pass_condition="Under 150 words. Short paragraphs (1-3 sentences). "
                          "White space between blocks. No walls of text.",
            scoring=_weighted(6, [
                ("word_count", "Under 150 words total", 0.50,
                 "1.0 if ≤150, 0.7 if ≤200, 0.3 if ≤250, 0.0 if >250"),
                ("scannability", "Short paragraphs, visual breaks", 0.50,
                 "1.0 if all paragraphs ≤3 sentences with breaks, 0.0 if wall of text"),
            ]),
            pass_examples=["5 short paragraphs, 120 words total"],
            fail_examples=["3 dense paragraphs, 300+ words"],
        ),
    ]

    return Rubric(
        task=task,
        domain="cold_outreach_email",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.80,
    )


# ============================================================================
# Task 2: Python CSV Parser
# ============================================================================

def build_csv_parser_rubric() -> Rubric:
    task = "Generate a Python function that parses messy CSV data with inconsistent delimiters and missing headers"

    criteria = [
        Criterion(
            id="code_correctness",
            category="functionality",
            description="Function handles the stated requirements: inconsistent delimiters, missing headers",
            pass_condition="Detects and handles comma/tab/pipe/semicolon delimiters. "
                          "Generates synthetic headers when missing. Doesn't crash on edge cases.",
            scoring=_weighted(12, [
                ("delimiter_detection", "Auto-detects or handles multiple delimiter types", 0.35,
                 "1.0 if auto-detects from data, 0.5 if parameterized, 0.0 if hardcoded"),
                ("header_handling", "Generates headers when missing, detects when present", 0.35,
                 "1.0 if auto-detects + generates, 0.5 if one or other, 0.0 if assumes headers"),
                ("edge_case_resilience", "Handles empty rows, mixed quoting, trailing delimiters", 0.30,
                 "% of edge cases handled without crash"),
            ]),
            pass_examples=["Uses csv.Sniffer for delimiter detection, heuristic for header presence"],
            fail_examples=["Hardcodes comma delimiter, assumes first row is header"],
        ),
        Criterion(
            id="code_robustness",
            category="reliability",
            description="Graceful error handling, doesn't silently corrupt data",
            pass_condition="Try/except with meaningful errors. Logs warnings for skipped rows. "
                          "Returns structured result with metadata (rows parsed, rows skipped, issues found).",
            scoring=_weighted(10, [
                ("error_handling", "Catches and reports errors meaningfully", 0.40,
                 "1.0 if structured error reporting, 0.5 if basic try/except, 0.0 if bare"),
                ("data_integrity", "Never silently drops or corrupts data", 0.35,
                 "1.0 if reports all anomalies, 0.0 if silently swallows"),
                ("return_metadata", "Returns parse stats (rows, skips, warnings)", 0.25,
                 "1.0 if structured result object, 0.5 if just data, 0.0 if raw list"),
            ]),
            pass_examples=["Returns ParseResult(data=..., warnings=[...], rows_skipped=2)"],
            fail_examples=["Bare except: pass, returns partial data silently"],
        ),
        Criterion(
            id="code_api_design",
            category="usability",
            description="Function signature is clean, well-typed, with sensible defaults",
            pass_condition="Type hints. Docstring with examples. Reasonable defaults. "
                          "Accepts str | Path | IO. Returns typed structure (not raw list).",
            scoring=_weighted(8, [
                ("type_hints", "Full type annotations on params and return", 0.35,
                 "1.0 if complete, 0.5 if partial, 0.0 if none"),
                ("docstring", "Docstring with description, args, returns, example", 0.30,
                 "1.0 if complete with example, 0.5 if basic, 0.0 if missing"),
                ("input_flexibility", "Accepts file path, string, or file object", 0.35,
                 "1.0 if multiple input types, 0.5 if one type, 0.0 if unclear"),
            ]),
            pass_examples=["def parse_csv(source: str | Path | IO, ...) -> ParseResult:"],
            fail_examples=["def parse(f):  # no types, no docs"],
        ),
        Criterion(
            id="code_idiomaticness",
            category="quality",
            description="Uses Python idioms and stdlib appropriately",
            pass_condition="Uses csv module (not regex-only). Leverages csv.Sniffer. "
                          "Dataclasses or TypedDict for results. No reinventing wheels.",
            scoring=_penalty(8, {
                "reinvents_csv_module": -3.0,
                "regex_only_parsing": -2.0,
                "no_type_structures": -1.5,
                "mutable_default_args": -1.5,
                "global_state": -2.0,
            }),
            pass_examples=["Builds on csv.reader/csv.Sniffer, returns dataclass"],
            fail_examples=["Regex-only CSV parsing, returns list of dicts with no structure"],
        ),
        Criterion(
            id="code_testability",
            category="quality",
            description="Code is structured for easy testing",
            pass_condition="Pure function (no side effects). Includes or suggests test cases. "
                          "Small composable helpers, not one monolith.",
            scoring=_weighted(6, [
                ("pure_function", "No side effects, deterministic", 0.40,
                 "1.0 if pure, 0.5 if minor side effects (logging ok), 0.0 if writes files"),
                ("modularity", "Logic decomposed into testable helpers", 0.30,
                 "1.0 if 3+ focused helpers, 0.5 if 2, 0.0 if monolith"),
                ("test_examples", "Includes example test cases or assertions", 0.30,
                 "1.0 if test cases included, 0.5 if doctest, 0.0 if none"),
            ]),
            pass_examples=["Separate detect_delimiter(), detect_headers(), parse_rows() + tests"],
            fail_examples=["Single 80-line function with no tests"],
        ),
    ]

    return Rubric(
        task=task,
        domain="code_generation",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 3: Executive Summary from Technical Blog Post
# ============================================================================

def build_exec_summary_rubric() -> Rubric:
    task = "Summarize a 2,000-word technical blog post into a 3-bullet executive summary"

    criteria = [
        Criterion(
            id="sum_compression",
            category="structure",
            description="Achieves 20:1+ compression — exactly 3 bullets, each 1-2 sentences",
            pass_condition="Exactly 3 bullets. Each bullet is 1-2 sentences. "
                          "Total under 100 words. No filler or hedging.",
            scoring=_weighted(10, [
                ("bullet_count", "Exactly 3 bullets", 0.30,
                 "1.0 if exactly 3, 0.5 if 2 or 4, 0.0 if other"),
                ("bullet_density", "Each bullet is 1-2 sentences, no filler", 0.35,
                 "% of bullets that are 1-2 tight sentences"),
                ("total_length", "Total under 100 words", 0.35,
                 "1.0 if ≤100 words, 0.7 if ≤130, 0.3 if ≤160, 0.0 if >160"),
            ]),
            pass_examples=["3 bullets, 85 words total, each bullet one declarative sentence + one supporting"],
            fail_examples=["5 bullets, 200 words, mini-paragraphs disguised as bullets"],
        ),
        Criterion(
            id="sum_fidelity",
            category="accuracy",
            description="Bullets capture the actual thesis and key claims — no hallucination",
            pass_condition="Bullet 1 = core thesis/finding. Bullet 2 = key evidence or mechanism. "
                          "Bullet 3 = implication or so-what. All traceable to source text.",
            scoring=_weighted(12, [
                ("thesis_capture", "First bullet nails the core thesis", 0.40,
                 "1.0 if captures central claim, 0.5 if tangential, 0.0 if wrong"),
                ("evidence_capture", "Key supporting evidence or mechanism included", 0.30,
                 "1.0 if strongest evidence cited, 0.5 if secondary, 0.0 if missing"),
                ("no_hallucination", "Nothing claimed that isn't in the source", 0.30,
                 "1.0 if all claims traceable, 0.0 per hallucinated claim"),
            ]),
            pass_examples=["Thesis + strongest data point + strategic implication, all from source"],
            fail_examples=["Vague paraphrase that could describe any post on the topic"],
        ),
        Criterion(
            id="sum_exec_value",
            category="utility",
            description="An executive could make a decision or take action from these 3 bullets alone",
            pass_condition="Answers 'so what?' and 'what do I do with this?'. Quantifies where possible. "
                          "Uses declarative framing, not passive/descriptive.",
            scoring=_weighted(10, [
                ("actionability", "Reader knows what to do or think differently after reading", 0.40,
                 "1.0 if clear action/decision implication, 0.5 if informational, 0.0 if academic"),
                ("quantification", "Numbers, magnitudes, or concrete specifics included", 0.30,
                 "1.0 if key numbers preserved, 0.5 if qualitative only, 0.0 if vague"),
                ("declarative_framing", "Bullets state claims, not 'the post discusses...'", 0.30,
                 "1.0 if all declarative, 0.5 if mixed, 0.0 if all descriptive/passive"),
            ]),
            pass_examples=["'LLM inference costs dropped 90% in 18 months — implications for build-vs-buy decisions in 2026'"],
            fail_examples=["'The author discusses various aspects of LLM cost trends'"],
        ),
        Criterion(
            id="sum_standalone",
            category="clarity",
            description="Summary is self-contained — no context needed to understand it",
            pass_condition="Doesn't reference 'the post' or 'the author'. Defines any jargon. "
                          "A reader with no context gets the point.",
            scoring=_penalty(6, {
                "references_source": -2.0,
                "undefined_jargon": -1.5,
                "assumes_context": -1.5,
                "passive_voice_dominant": -1.0,
            }),
            pass_examples=["Self-contained claims that work as standalone intelligence"],
            fail_examples=["'The author argues that...' or 'This post explores...'"],
        ),
    ]

    return Rubric(
        task=task,
        domain="summarization",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 4: SQL Query — Top 10 Customers by LTV
# ============================================================================

def build_sql_ltv_rubric() -> Rubric:
    task = "Create a SQL query to find the top 10 customers by lifetime value excluding refunds, from a schema you define"

    criteria = [
        Criterion(
            id="sql_schema",
            category="design",
            description="Schema is realistic, normalized, and supports the query requirements",
            pass_condition="Separate customers, orders, order_items, payments/refunds tables. "
                          "Proper PKs/FKs. Realistic column types. Refunds modeled distinctly from payments.",
            scoring=_weighted(10, [
                ("normalization", "Proper 3NF with PKs/FKs", 0.30,
                 "1.0 if 3NF, 0.5 if some denormalization, 0.0 if flat"),
                ("refund_modeling", "Refunds modeled as distinct records, not negative amounts", 0.35,
                 "1.0 if refund table or refund_type flag, 0.5 if negative amounts, 0.0 if not modeled"),
                ("realistic_columns", "Realistic types, constraints, timestamps", 0.35,
                 "% of tables with appropriate types and constraints"),
            ]),
            pass_examples=["customers, orders, order_items, payments (with type: 'charge'|'refund') + indexes"],
            fail_examples=["Single 'transactions' table with all data flattened"],
        ),
        Criterion(
            id="sql_correctness",
            category="functionality",
            description="Query returns correct results — top 10 by LTV excluding refunds",
            pass_condition="Correctly aggregates payments minus refunds per customer. "
                          "Uses proper GROUP BY, HAVING, ORDER BY DESC LIMIT 10. "
                          "Handles NULL edge cases.",
            scoring=_weighted(12, [
                ("aggregation_logic", "SUM(charges) - SUM(refunds) or equivalent", 0.40,
                 "1.0 if correct LTV calc, 0.5 if close, 0.0 if wrong"),
                ("grouping", "Proper GROUP BY customer with ORDER BY + LIMIT", 0.30,
                 "1.0 if correct, 0.0 if missing or wrong"),
                ("null_handling", "COALESCE or equivalent for customers with no refunds", 0.30,
                 "1.0 if handles nulls, 0.5 if partially, 0.0 if would fail on nulls"),
            ]),
            pass_examples=["COALESCE(SUM(CASE WHEN type='charge' THEN amount END), 0) - COALESCE(SUM(CASE WHEN type='refund' THEN amount END), 0)"],
            fail_examples=["SELECT * FROM customers ORDER BY amount — no aggregation"],
        ),
        Criterion(
            id="sql_readability",
            category="quality",
            description="Query is well-formatted, commented, and uses CTEs appropriately",
            pass_condition="Uses CTEs for complex subqueries. Consistent formatting. "
                          "Meaningful aliases. Comments on non-obvious logic.",
            scoring=_weighted(8, [
                ("cte_usage", "Uses CTEs for readability instead of nested subqueries", 0.35,
                 "1.0 if CTEs for distinct logical steps, 0.5 if inline subqueries, 0.0 if spaghetti"),
                ("formatting", "Consistent capitalization, indentation, line breaks", 0.30,
                 "1.0 if clean formatting, 0.5 if mostly ok, 0.0 if unformatted"),
                ("documentation", "Comments on key logic, meaningful aliases", 0.35,
                 "1.0 if commented + good aliases, 0.5 if one, 0.0 if neither"),
            ]),
            pass_examples=["WITH customer_charges AS (...), customer_refunds AS (...) SELECT ..."],
            fail_examples=["One-liner with nested subqueries and single-letter aliases"],
        ),
        Criterion(
            id="sql_performance",
            category="optimization",
            description="Query would perform well at scale (millions of rows)",
            pass_condition="Suggests or includes appropriate indexes. Avoids SELECT *. "
                          "Doesn't use correlated subqueries. Notes on execution plan.",
            scoring=_penalty(6, {
                "select_star": -1.5,
                "correlated_subquery": -2.0,
                "missing_index_suggestion": -1.0,
                "cartesian_join_risk": -2.5,
                "function_on_indexed_column": -1.0,
            }),
            pass_examples=["Index on payments(customer_id, type, amount), avoids correlated subqueries"],
            fail_examples=["SELECT * with correlated subquery per customer row"],
        ),
    ]

    return Rubric(
        task=task,
        domain="sql_query",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 5: Counterargument — AGI Before 2030
# ============================================================================

def build_counterargument_rubric() -> Rubric:
    task = "Write a counterargument to the claim 'AGI will arrive before 2030'"

    criteria = [
        Criterion(
            id="arg_steelman",
            category="intellectual_honesty",
            description="Steelmans the original claim before countering it",
            pass_condition="First paragraph presents the strongest version of the AGI-by-2030 case. "
                          "Cites real scaling results, benchmarks, expert proponents. "
                          "Shows the reader you understand why smart people believe this.",
            scoring=_weighted(10, [
                ("steelman_quality", "Presents strongest version of the claim", 0.50,
                 "1.0 if cites specific results/proponents, 0.5 if generic, 0.0 if strawman"),
                ("specific_evidence", "References real benchmarks, papers, or expert positions", 0.30,
                 "1.0 if 2+ specific references, 0.5 if 1, 0.0 if none"),
                ("good_faith", "Reader feels the argument was fairly represented", 0.20,
                 "1.0 if fair, 0.0 if dismissive/strawman"),
            ]),
            pass_examples=["'The case for AGI by 2030 is stronger than critics admit: GPT-4 to o3 showed...'"],
            fail_examples=["'Some people naively believe AGI is coming soon, but...'"],
        ),
        Criterion(
            id="arg_counter_quality",
            category="argumentation",
            description="Counterarguments are specific, non-obvious, and empirically grounded",
            pass_condition="3+ distinct counter-threads. At least one challenges the definition of AGI. "
                          "At least one is empirical (benchmarking issues, capability gaps). "
                          "At least one is structural (alignment, deployment, regulation).",
            scoring=_weighted(12, [
                ("argument_count", "3+ distinct counter-threads", 0.20,
                 "1.0 if 3+, 0.5 if 2, 0.0 if 1"),
                ("definitional_challenge", "Challenges what 'AGI' means and why it matters", 0.25,
                 "1.0 if substantive definitional argument, 0.0 if skips it"),
                ("empirical_grounding", "Cites specific capability gaps, benchmark limitations", 0.30,
                 "1.0 if specific gaps with evidence, 0.5 if general, 0.0 if hand-wavy"),
                ("structural_barriers", "Addresses alignment, regulation, deployment realities", 0.25,
                 "1.0 if specific structural argument, 0.5 if mentioned, 0.0 if absent"),
            ]),
            pass_examples=["Definitional ambiguity + benchmark saturation without real-world transfer + regulatory friction"],
            fail_examples=["'AI is overhyped' repeated three different ways"],
        ),
        Criterion(
            id="arg_nuance",
            category="sophistication",
            description="Avoids absolutism — acknowledges uncertainty and conditions",
            pass_condition="Uses probabilistic language. Identifies conditions under which the claim "
                          "could be true. Distinguishes 'narrow AGI' from 'transformative AI'. "
                          "Doesn't claim to know the answer.",
            scoring=_penalty(8, {
                "absolutist_claim": -2.5,
                "dismisses_without_evidence": -2.0,
                "ignores_counterexamples": -1.5,
                "no_uncertainty_acknowledgment": -2.0,
                "appeal_to_authority_only": -1.0,
            }),
            pass_examples=["'AGI by 2030 is possible but improbable — here's why the base rate for such predictions is poor'"],
            fail_examples=["'AGI will definitely not happen by 2030'"],
        ),
        Criterion(
            id="arg_readability",
            category="communication",
            description="Well-structured, scannable, persuasive prose",
            pass_condition="Clear thesis in first paragraph. Each counter-thread in its own section. "
                          "Conclusion synthesizes. Under 800 words.",
            scoring=_weighted(6, [
                ("structure", "Thesis → steelman → counters → synthesis", 0.40,
                 "1.0 if clear structure, 0.5 if partially organized, 0.0 if stream of consciousness"),
                ("concision", "Under 800 words, no padding", 0.30,
                 "1.0 if ≤800, 0.7 if ≤1000, 0.0 if >1200"),
                ("persuasive_flow", "Builds momentum, ends strong", 0.30,
                 "1.0 if compelling arc, 0.5 if flat, 0.0 if scattered"),
            ]),
            pass_examples=["700 words, clear sections, ends with a memorable reframe"],
            fail_examples=["1500-word stream of consciousness with no structure"],
        ),
    ]

    return Rubric(
        task=task,
        domain="argumentation",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.80,
    )


# ============================================================================
# Task 6: JSON Schema — Multi-tenant SaaS Billing
# ============================================================================

def build_billing_schema_rubric() -> Rubric:
    task = "Design a JSON schema for a multi-tenant SaaS billing system supporting usage-based and seat-based pricing"

    criteria = [
        Criterion(
            id="schema_completeness",
            category="design",
            description="Schema covers all required entities and pricing models",
            pass_condition="Entities: tenant, plan, subscription, usage_record, invoice, line_item. "
                          "Pricing models: per-seat, usage-based (metered), tiered, hybrid. "
                          "Billing cycles, proration, trial periods.",
            scoring=_weighted(12, [
                ("entity_coverage", "All required entities present", 0.30,
                 "% of required entities modeled (tenant, plan, subscription, usage, invoice, line_item)"),
                ("pricing_model_support", "Both seat-based and usage-based modeled", 0.35,
                 "1.0 if both + hybrid, 0.75 if both, 0.5 if one, 0.0 if neither"),
                ("billing_lifecycle", "Cycles, proration, trials, upgrades/downgrades", 0.35,
                 "% of lifecycle events modeled (create, upgrade, downgrade, cancel, prorate, trial)"),
            ]),
            pass_examples=["Plan with pricing_model: {type: 'hybrid', seat_price: ..., metered_dimensions: [...]}"],
            fail_examples=["Just 'plan' and 'subscription' with flat price field"],
        ),
        Criterion(
            id="schema_correctness",
            category="quality",
            description="Valid JSON Schema with proper types, constraints, references",
            pass_condition="Valid JSON Schema (draft-07+). Uses $ref for reuse. "
                          "Required fields marked. Enums for constrained values. "
                          "Proper date-time formats.",
            scoring=_weighted(10, [
                ("schema_validity", "Valid JSON Schema syntax", 0.30,
                 "1.0 if valid draft-07+, 0.5 if mostly valid, 0.0 if invalid"),
                ("ref_usage", "Uses $ref for reusable definitions", 0.25,
                 "1.0 if DRY with $ref, 0.5 if some reuse, 0.0 if duplicated"),
                ("constraint_quality", "Proper enums, required, formats, patterns", 0.45,
                 "% of fields with appropriate constraints"),
            ]),
            pass_examples=["$ref to shared 'money' type with currency+amount, enum for billing_interval"],
            fail_examples=["Freeform JSON with no type constraints"],
        ),
        Criterion(
            id="schema_extensibility",
            category="architecture",
            description="Schema is extensible without breaking changes",
            pass_condition="Uses additionalProperties judiciously. Versioned. "
                          "Metered dimensions are a list (not hardcoded). "
                          "Custom metadata fields supported.",
            scoring=_weighted(8, [
                ("metered_extensibility", "Usage dimensions are dynamic, not hardcoded", 0.40,
                 "1.0 if array of dimension objects, 0.5 if a few named fields, 0.0 if hardcoded"),
                ("metadata_support", "Custom metadata/extension points", 0.30,
                 "1.0 if metadata object on key entities, 0.0 if closed"),
                ("versioning", "Schema version field or versioning strategy", 0.30,
                 "1.0 if versioned, 0.0 if not"),
            ]),
            pass_examples=["metered_dimensions: [{id, unit, tiers: [...]}] — add new dimensions without schema change"],
            fail_examples=["Hardcoded 'api_calls' and 'storage_gb' fields"],
        ),
        Criterion(
            id="schema_realworld",
            category="practicality",
            description="Schema reflects real billing system patterns (Stripe-informed, not academic)",
            pass_condition="Models concepts from real systems: idempotency keys, "
                          "invoice status lifecycle, webhook events, currency handling. "
                          "Avoids naive patterns (storing calculated totals without line items).",
            scoring=_penalty(8, {
                "no_currency_handling": -2.0,
                "calculated_total_without_line_items": -2.0,
                "no_idempotency": -1.0,
                "no_invoice_status_lifecycle": -1.5,
                "naive_date_handling": -1.5,
                "single_currency_assumption": -1.0,
            }),
            pass_examples=["Invoice with status enum (draft→open→paid→void), line_items array, currency code per amount"],
            fail_examples=["Invoice with just 'total: 99.99' and no line items"],
        ),
    ]

    return Rubric(
        task=task,
        domain="schema_design",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 7: Explain Transformer Attention to a 16-Year-Old
# ============================================================================

def build_explanation_rubric() -> Rubric:
    task = "Explain transformer attention mechanisms to a smart 16-year-old"

    criteria = [
        Criterion(
            id="expl_accuracy",
            category="correctness",
            description="Technical content is correct — no simplification-induced errors",
            pass_condition="Query/Key/Value framework explained correctly. "
                          "Dot product similarity is accurate. Softmax described correctly. "
                          "Multi-head attention's purpose is right.",
            scoring=_weighted(12, [
                ("qkv_correctness", "Q/K/V roles explained accurately", 0.35,
                 "1.0 if correct mechanism, 0.5 if metaphor-only, 0.0 if wrong"),
                ("attention_math", "Dot product + softmax pipeline correct", 0.35,
                 "1.0 if mechanism right, 0.5 if hand-wavy but directionally correct, 0.0 if wrong"),
                ("multihead_purpose", "Why multiple heads matter", 0.30,
                 "1.0 if explains different relationship types, 0.5 if mentions it, 0.0 if absent"),
            ]),
            pass_examples=["'Each word asks a question (query), advertises what it knows (key), and shares details (value)'"],
            fail_examples=["'Attention is when the model focuses on important words' — no mechanism"],
        ),
        Criterion(
            id="expl_accessibility",
            category="audience_fit",
            description="A smart 16-year-old actually understands it after reading",
            pass_condition="No unexplained jargon. Uses analogies from their world. "
                          "Builds from familiar concepts (search, recommendation) to new ones. "
                          "Math level: algebra ok, linear algebra explained if used.",
            scoring=_weighted(10, [
                ("jargon_handling", "All technical terms explained or avoided", 0.30,
                 "1.0 if all explained, 0.5 if most, 0.0 if jargon-heavy"),
                ("analogy_quality", "Uses relatable analogies (social media, school, etc.)", 0.35,
                 "1.0 if memorable analogy that maps correctly, 0.5 if generic, 0.0 if none"),
                ("progressive_complexity", "Builds from simple to complex", 0.35,
                 "1.0 if clear scaffold, 0.5 if some structure, 0.0 if jumps to hard parts"),
            ]),
            pass_examples=["Starts with 'imagine searching for a video on YouTube' → builds to Q/K/V"],
            fail_examples=["'Attention computes softmax(QK^T/√d_k)V' with no unpacking"],
        ),
        Criterion(
            id="expl_engagement",
            category="communication",
            description="Explanation is engaging — a 16-year-old would actually read to the end",
            pass_condition="Conversational tone. Not condescending. Includes a 'whoa' moment. "
                          "Under 600 words. Has a hook in the first sentence.",
            scoring=_weighted(8, [
                ("hook", "First sentence creates curiosity", 0.30,
                 "1.0 if compelling hook, 0.5 if adequate, 0.0 if textbook opening"),
                ("tone", "Conversational, not textbook or condescending", 0.35,
                 "1.0 if natural, 0.5 if slightly formal, 0.0 if textbook/patronizing"),
                ("concision", "Under 600 words, no padding", 0.35,
                 "1.0 if ≤600, 0.7 if ≤800, 0.0 if >1000"),
            ]),
            pass_examples=["'You know how autocomplete seems to read your mind? Here's the trick...'"],
            fail_examples=["'Attention mechanisms are a fundamental component of transformer architectures...'"],
        ),
        Criterion(
            id="expl_completeness",
            category="coverage",
            description="Covers the essential pieces without going too deep",
            pass_condition="Covers: why attention exists (context problem), how it works (Q/K/V), "
                          "why it matters (parallel processing, long-range dependencies). "
                          "Doesn't require covering positional encoding, layer norm, etc.",
            scoring=_weighted(6, [
                ("motivation", "Explains why attention was invented (the problem it solves)", 0.35,
                 "1.0 if clear problem statement, 0.5 if implied, 0.0 if jumps to mechanism"),
                ("mechanism", "How attention works at an intuitive level", 0.35,
                 "1.0 if clear mechanism, 0.0 if vague"),
                ("significance", "Why it matters / what it enabled", 0.30,
                 "1.0 if connects to real impact, 0.5 if mentioned, 0.0 if absent"),
            ]),
            pass_examples=["Problem (RNNs forget) → Mechanism (Q/K/V attention) → Impact (ChatGPT, translation)"],
            fail_examples=["Deep dive into multi-head attention math with no motivation"],
        ),
    ]

    return Rubric(
        task=task,
        domain="explanation",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.80,
    )


# ============================================================================
# Task 8: Startup Names — AI Contract Review
# ============================================================================

def build_naming_rubric() -> Rubric:
    task = "Generate 5 names for a startup that does AI-powered contract review for mid-market law firms"

    criteria = [
        Criterion(
            id="name_count",
            category="structure",
            description="Exactly 5 names provided, each with rationale",
            pass_condition="Exactly 5 names. Each has 1-2 sentence rationale explaining "
                          "the thinking behind it.",
            scoring=_binary(4),
            pass_examples=["5 names, each with explanation of etymology and positioning"],
            fail_examples=["3 names with no explanation, or 10 names dumped"],
        ),
        Criterion(
            id="name_memorability",
            category="quality",
            description="Names are memorable, pronounceable, and pass the 'phone test'",
            pass_condition="Each name: ≤3 syllables preferred, no awkward letter combos, "
                          "survives being spoken aloud, doesn't require spelling out.",
            scoring=_weighted(10, [
                ("pronounceability", "Names can be said aloud without confusion", 0.40,
                 "% of names that pass the phone test (say it, spell it)"),
                ("brevity", "Short, punchy — ideally ≤3 syllables", 0.30,
                 "% of names at ≤3 syllables"),
                ("distinctiveness", "Doesn't blend in with existing brands", 0.30,
                 "% of names that are distinct from obvious competitors"),
            ]),
            pass_examples=["'Clause' — 1 syllable, legal meaning, memorable"],
            fail_examples=["'IntelliLegalContractAI' — unmemorable, generic compound"],
        ),
        Criterion(
            id="name_domain_resonance",
            category="relevance",
            description="Names signal legal/contract/AI domain without being generic",
            pass_condition="Names evoke precision, trust, intelligence, or legal concepts. "
                          "Not generic 'AI' prefix/suffix spam. "
                          "Would feel at home on a law firm partner's desk.",
            scoring=_weighted(10, [
                ("domain_signal", "Evokes legal/contract/precision without being literal", 0.40,
                 "% of names with subtle domain resonance"),
                ("avoids_generic_ai", "No 'AI' prefix/suffix, no '-ify', no 'Smart[X]'", 0.30,
                 "% of names avoiding generic tech naming patterns"),
                ("trust_register", "Would a law firm partner take a meeting with this company?", 0.30,
                 "% of names that feel professional enough for legal market"),
            ]),
            pass_examples=["'Redline' — contract review term, implies precision and editing"],
            fail_examples=["'ContractAI', 'SmartReview', 'LegalBot'"],
        ),
        Criterion(
            id="name_availability",
            category="practicality",
            description="Names are likely available — .com plausible, not taken by major brands",
            pass_condition="At least 3/5 names have plausible .com availability (not common English words). "
                          "None are existing well-known brands. Notes on availability included.",
            scoring=_weighted(6, [
                ("domain_plausibility", "Names likely have .com available or reasonable variant", 0.50,
                 "% of names where .com is plausible (not a common English word)"),
                ("no_trademark_conflicts", "Not an existing well-known brand name", 0.50,
                 "% of names with no obvious trademark conflict"),
            ]),
            pass_examples=["'Clausebound' — coined word, .com likely available"],
            fail_examples=["'Scout' — common word, definitely taken"],
        ),
        Criterion(
            id="name_variety",
            category="range",
            description="Names span different naming strategies — not all the same pattern",
            pass_condition="Mix of approaches: metaphorical, coined, real-word-repurposed, "
                          "compound, classical/Latin root. At least 3 different strategies.",
            scoring=_weighted(6, [
                ("strategy_diversity", "At least 3 different naming strategies used", 0.50,
                 "1.0 if 4+ strategies, 0.75 if 3, 0.5 if 2, 0.0 if all same"),
                ("range_of_tone", "Mix of serious/approachable/bold", 0.50,
                 "1.0 if clear tonal range, 0.5 if some variation, 0.0 if monotone"),
            ]),
            pass_examples=["Metaphorical (Redline) + coined (Clausefy) + classical (Lex Machina) + compound (Inkwell)"],
            fail_examples=["5 variations of '[Legal word] + AI'"],
        ),
    ]

    return Rubric(
        task=task,
        domain="creative_naming",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.75,
    )


# ============================================================================
# Task 9: Bash Script — PostgreSQL Backup to S3
# ============================================================================

def build_bash_backup_rubric() -> Rubric:
    task = "Write a bash script that backs up a PostgreSQL database to S3 with rotation, logging, and error notifications"

    criteria = [
        Criterion(
            id="bash_correctness",
            category="functionality",
            description="Script performs correct pg_dump → compress → upload → rotate pipeline",
            pass_condition="Uses pg_dump with appropriate flags. Compresses output (gzip/zstd). "
                          "Uploads to S3 with aws cli. Rotates old backups by age or count.",
            scoring=_weighted(12, [
                ("dump_command", "pg_dump with correct flags (--format, --no-owner, etc.)", 0.30,
                 "1.0 if pg_dump with appropriate format flags, 0.5 if basic, 0.0 if wrong"),
                ("compression", "Output compressed before upload", 0.20,
                 "1.0 if compressed (gzip/zstd), 0.0 if raw SQL upload"),
                ("s3_upload", "aws s3 cp/sync with correct path and options", 0.25,
                 "1.0 if correct aws s3 cp with proper path, 0.0 if wrong"),
                ("rotation", "Deletes backups older than N days or keeps last N", 0.25,
                 "1.0 if implemented correctly, 0.5 if partially, 0.0 if missing"),
            ]),
            pass_examples=["pg_dump -Fc | gzip > backup.gz && aws s3 cp ... && find/delete old"],
            fail_examples=["pg_dump with no compression, no rotation logic"],
        ),
        Criterion(
            id="bash_safety",
            category="reliability",
            description="Script is safe — set -euo pipefail, no secrets in code, cleanup on failure",
            pass_condition="set -euo pipefail. Trap for cleanup. No hardcoded passwords. "
                          "Uses .pgpass or env vars. Temp files cleaned up.",
            scoring=_penalty(10, {
                "no_set_e": -2.0,
                "no_pipefail": -1.5,
                "hardcoded_password": -3.0,
                "no_trap_cleanup": -1.5,
                "no_temp_file_cleanup": -1.0,
                "unquoted_variables": -1.0,
                "no_lockfile": -0.5,
            }),
            pass_examples=["set -euo pipefail, trap cleanup EXIT, reads creds from env"],
            fail_examples=["No error handling, password in script, temp files left behind"],
        ),
        Criterion(
            id="bash_logging",
            category="observability",
            description="Comprehensive logging with timestamps and log levels",
            pass_condition="Timestamped log function. Logs start/success/failure/rotation. "
                          "Writes to file AND stdout. Includes backup size and duration.",
            scoring=_weighted(8, [
                ("log_function", "Dedicated log function with timestamps", 0.30,
                 "1.0 if log() function with ISO timestamps, 0.5 if echo with date, 0.0 if plain echo"),
                ("log_completeness", "Logs all key events (start, size, duration, rotate, done)", 0.35,
                 "% of key events logged"),
                ("log_destination", "Writes to both file and stdout", 0.35,
                 "1.0 if tee to file + stdout, 0.5 if one, 0.0 if neither"),
            ]),
            pass_examples=["log() { echo \"[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [$1] $2\" | tee -a $LOG; }"],
            fail_examples=["Random echo statements with no timestamps"],
        ),
        Criterion(
            id="bash_notifications",
            category="alerting",
            description="Error notifications via practical channel (email, Slack, PagerDuty)",
            pass_condition="On failure: sends notification with error details and context. "
                          "Configurable notification channel. Includes backup name, error message, timestamp.",
            scoring=_weighted(8, [
                ("notification_impl", "Actually sends notification on failure", 0.40,
                 "1.0 if implemented (curl to Slack, mail, etc.), 0.0 if TODO/placeholder"),
                ("error_context", "Notification includes useful context (timestamp, db, error)", 0.35,
                 "1.0 if rich context, 0.5 if basic, 0.0 if just 'backup failed'"),
                ("configurability", "Channel/endpoint configurable via env var", 0.25,
                 "1.0 if configurable, 0.5 if hardcoded but works, 0.0 if neither"),
            ]),
            pass_examples=["Slack webhook with formatted message including db name, error, and log tail"],
            fail_examples=["# TODO: add notifications"],
        ),
        Criterion(
            id="bash_configurability",
            category="usability",
            description="Script is configurable via environment variables with sensible defaults",
            pass_condition="Key params via env vars: DB_NAME, S3_BUCKET, RETENTION_DAYS, etc. "
                          "Defaults provided. Usage/help flag. Validates required vars.",
            scoring=_weighted(6, [
                ("env_var_config", "Key params from env vars with defaults", 0.40,
                 "% of configurable params using env vars with fallback defaults"),
                ("validation", "Validates required vars exist before starting", 0.30,
                 "1.0 if checks all required vars, 0.5 if some, 0.0 if none"),
                ("help_flag", "--help flag with usage instructions", 0.30,
                 "1.0 if --help works, 0.0 if no help"),
            ]),
            pass_examples=["DB_NAME=${DB_NAME:?'DB_NAME required'}, RETENTION=${RETENTION_DAYS:-30}"],
            fail_examples=["Hardcoded db name, bucket, and retention in script body"],
        ),
    ]

    return Rubric(
        task=task,
        domain="bash_scripting",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 10: 1-Page Investment Memo — Defense Drone Series A
# ============================================================================

def build_investment_memo_rubric() -> Rubric:
    task = "Draft a 1-page investment memo on a hypothetical Series A company in the defense drone space"

    criteria = [
        Criterion(
            id="memo_structure",
            category="format",
            description="Follows standard 1-page memo format with all required sections",
            pass_condition="Sections: Company Overview, Market Opportunity, Product/Technology, "
                          "Team, Traction, Deal Terms, Key Risks, Recommendation. "
                          "Fits on one page (~500-700 words).",
            scoring=_weighted(10, [
                ("section_coverage", "All required sections present", 0.35,
                 "% of required sections (overview, market, product, team, traction, terms, risks, rec)"),
                ("page_constraint", "Fits on one page (500-700 words)", 0.30,
                 "1.0 if 500-700 words, 0.7 if 700-850, 0.3 if 400-500, 0.0 if >900"),
                ("scannable_format", "Headers, bullets within sections, dense but readable", 0.35,
                 "1.0 if scannable with clear visual hierarchy, 0.0 if wall of text"),
            ]),
            pass_examples=["8 sections, 650 words, each section 2-4 bullet points"],
            fail_examples=["3-page narrative essay, or 200-word skim"],
        ),
        Criterion(
            id="memo_market",
            category="analysis",
            description="Market opportunity is sized and specific to defense drones, not generic TAM",
            pass_condition="SAM/SOM, not just TAM. Specific to defense drone segment. "
                          "Cites or constructs credible numbers. Identifies tailwinds "
                          "(DoD budget trends, Ukraine lessons, NDAA provisions).",
            scoring=_weighted(10, [
                ("market_specificity", "Defense drone SAM, not generic 'drone market'", 0.35,
                 "1.0 if defense-specific SAM/SOM, 0.5 if TAM only, 0.0 if generic"),
                ("credible_sizing", "Numbers are plausible with cited or constructed basis", 0.30,
                 "1.0 if sourced/constructed, 0.5 if asserted, 0.0 if absent"),
                ("tailwind_identification", "Specific policy/geopolitical tailwinds cited", 0.35,
                 "% of relevant tailwinds identified (DoD budget, NDAA, Ukraine, Replicator)"),
            ]),
            pass_examples=["'Defense sUAS SAM: $8B by 2028 (up from $3B), driven by DoD Replicator initiative and FY26 NDAA line items'"],
            fail_examples=["'The global drone market is expected to reach $50B by 2030'"],
        ),
        Criterion(
            id="memo_thesis",
            category="conviction",
            description="Investment thesis is crisp — clear 'why this company, why now'",
            pass_condition="2-3 sentence thesis that answers: What's the insight? "
                          "Why is this team positioned? What's the timing catalyst? "
                          "Must be specific enough that it couldn't apply to any defense startup.",
            scoring=_weighted(10, [
                ("insight_clarity", "Core insight is specific and non-obvious", 0.40,
                 "1.0 if specific insight, 0.5 if generic but directionally right, 0.0 if boilerplate"),
                ("team_match", "Why this team specifically is positioned to win", 0.30,
                 "1.0 if specific team-market fit, 0.5 if generic team praise, 0.0 if absent"),
                ("timing_catalyst", "Clear 'why now' with specific catalyst", 0.30,
                 "1.0 if specific timing argument, 0.5 if vague, 0.0 if absent"),
            ]),
            pass_examples=["'DoD is shifting from $50M primes-built systems to $500K attritable drones — [Company] has the only NDAA-compliant autonomy stack that integrates with existing C2 systems, built by ex-Anduril engineers who shipped the first production Altius system.'"],
            fail_examples=["'Defense is a big market and drones are the future.'"],
        ),
        Criterion(
            id="memo_risks",
            category="diligence",
            description="Key risks are honest, specific, and include mitigants",
            pass_condition="3-5 real risks (not strawmen). At least one each: market risk, "
                          "execution risk, regulatory/ITAR risk. Each has a mitigant or monitoring plan.",
            scoring=_weighted(8, [
                ("risk_quality", "Risks are real and specific, not generic", 0.40,
                 "% of risks that are specific to this company/market"),
                ("risk_coverage", "Market, execution, and regulatory/ITAR risks all addressed", 0.30,
                 "1.0 if all 3 categories, 0.5 if 2, 0.0 if 1"),
                ("mitigants", "Each risk has a plausible mitigant or monitoring plan", 0.30,
                 "% of risks with stated mitigants"),
            ]),
            pass_examples=["'ITAR compliance burden limits sales velocity — mitigant: CTO has existing DSP-5/DSP-73 experience from Lockheed tenure'"],
            fail_examples=["'Risk: competition. Risk: market might not grow.'"],
        ),
        Criterion(
            id="memo_deal_terms",
            category="practicality",
            description="Deal terms are realistic and internally consistent",
            pass_condition="Pre-money valuation, round size, lead investor type, and use of funds. "
                          "Values are stage-appropriate (Series A defense: $15-40M pre). "
                          "Use of funds is specific (hiring, ITAR facility, production line).",
            scoring=_weighted(6, [
                ("completeness", "Valuation, round size, ownership target stated", 0.40,
                 "% of deal terms present"),
                ("stage_appropriateness", "Values are realistic for Series A defense startup", 0.30,
                 "1.0 if realistic, 0.5 if slightly off, 0.0 if unrealistic"),
                ("use_of_funds", "Specific allocation of capital", 0.30,
                 "1.0 if specific breakdown, 0.5 if vague, 0.0 if absent"),
            ]),
            pass_examples=["'$20M Series A at $60M pre. Use: 40% eng/autonomy, 25% ITAR facility, 20% BD, 15% ops'"],
            fail_examples=["'Raising a Series A at a good valuation'"],
        ),
    ]

    return Rubric(
        task=task,
        domain="investment_memo",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 11: Incident Postmortem — Cascading Microservice Failure
# ============================================================================

def build_incident_postmortem_rubric() -> Rubric:
    task = (
        "Write a blameless incident postmortem for a 4-hour production outage caused by "
        "a cascading failure across 3 microservices, including timeline, root cause, "
        "contributing factors, and action items"
    )

    criteria = [
        Criterion(
            id="pm_timeline",
            category="structure",
            description="Timeline is detailed, minute-level, and covers detection → mitigation → resolution",
            pass_condition="Timestamped entries from first alert to all-clear. Covers detection, "
                          "escalation, diagnosis attempts, mitigation, resolution, follow-up. "
                          "At least 10 distinct timeline entries spanning the 4-hour window.",
            scoring=_weighted(12, [
                ("granularity", "Minute-level timestamps with clear event descriptions", 0.30,
                 "1.0 if minute-level with 10+ entries, 0.5 if hourly, 0.0 if vague"),
                ("coverage", "Covers full lifecycle: detect → escalate → diagnose → mitigate → resolve", 0.35,
                 "% of lifecycle phases covered"),
                ("cascade_visibility", "Shows how failure propagated across the 3 services", 0.35,
                 "1.0 if cascade chain is explicit with per-service impact, 0.0 if lumped together"),
            ]),
            pass_examples=["14:03 — Auth service latency spikes to 8s → 14:07 — Payment service circuit breaker trips → 14:12 — Order service queue depth exceeds 50K"],
            fail_examples=["'Around 2pm things started going wrong and by 6pm we fixed it'"],
        ),
        Criterion(
            id="pm_root_cause",
            category="analysis",
            description="Root cause analysis is technically precise and distinguishes root from contributing causes",
            pass_condition="Identifies a single root cause with technical specificity. "
                          "Separates contributing factors (monitoring gaps, config drift, missing circuit breakers). "
                          "Uses 5-whys or similar structured reasoning.",
            scoring=_weighted(12, [
                ("root_cause_precision", "Specific technical root cause, not vague hand-waving", 0.35,
                 "1.0 if pinpoints exact failure (e.g., connection pool exhaustion due to X), 0.0 if vague"),
                ("contributing_factors", "At least 3 contributing factors identified separately", 0.30,
                 "1.0 if 3+ factors clearly separated from root cause, 0.5 if mixed, 0.0 if absent"),
                ("structured_reasoning", "Uses 5-whys, fault tree, or similar analysis method", 0.35,
                 "1.0 if structured analysis visible, 0.5 if implicit, 0.0 if just narrative"),
            ]),
            pass_examples=["Root cause: connection pool leak in auth-service v2.3.1 (PR #847) when Redis failover triggers reconnect storm. Contributing: no connection pool monitoring, stale circuit breaker config, no load shedding."],
            fail_examples=["'The database went down and caused an outage'"],
        ),
        Criterion(
            id="pm_blamelessness",
            category="tone",
            description="Postmortem is genuinely blameless — focuses on systems, not individuals",
            pass_condition="No person named as cause. Uses 'the system' not 'the engineer'. "
                          "Frames gaps as process/tooling failures. Acknowledges what went right.",
            scoring=_penalty(10, {
                "names_individual_as_cause": -4.0,
                "passive_aggressive_blame": -3.0,
                "no_what_went_well_section": -1.5,
                "punitive_action_items": -2.0,
                "finger_pointing_language": -2.0,
            }),
            pass_examples=["'The deployment pipeline lacked a canary stage' not 'Bob deployed without testing'"],
            fail_examples=["'The on-call engineer failed to notice the alert for 30 minutes'"],
        ),
        Criterion(
            id="pm_action_items",
            category="remediation",
            description="Action items are specific, owned, prioritized, and time-bound",
            pass_condition="At least 5 action items. Each has: what, who (role not name), priority (P0-P2), "
                          "deadline, and success metric. Mix of immediate fixes and systemic improvements.",
            scoring=_weighted(10, [
                ("specificity", "Each action item is a concrete deliverable, not vague", 0.30,
                 "1.0 if all SMART-style, 0.5 if mixed, 0.0 if vague"),
                ("ownership_and_deadline", "Each item has owner (role) and timeline", 0.30,
                 "% of items with both owner and deadline"),
                ("prioritization", "Items prioritized by impact, mix of quick fixes and systemic", 0.20,
                 "1.0 if P0/P1/P2 with rationale, 0.0 if unprioritized"),
                ("prevention_focus", "Items prevent recurrence, not just fix symptoms", 0.20,
                 "1.0 if systemic prevention, 0.5 if just patches, 0.0 if none"),
            ]),
            pass_examples=["P0: Add connection pool monitoring with alert at 80% utilization — Platform team — 1 week — metric: alert fires in staging test"],
            fail_examples=["'Fix the bug', 'Be more careful', 'Add monitoring'"],
        ),
        Criterion(
            id="pm_impact_quantification",
            category="completeness",
            description="Impact is quantified across customer, business, and technical dimensions",
            pass_condition="Quantifies: users affected, error rate, revenue impact, SLA breach, "
                          "and customer-facing symptoms. Distinguishes partial vs total outage.",
            scoring=_weighted(8, [
                ("customer_impact", "Number of users/requests affected, error rates", 0.35,
                 "1.0 if specific numbers, 0.5 if estimates, 0.0 if 'some users'"),
                ("business_impact", "Revenue/SLA implications quantified", 0.35,
                 "1.0 if dollar/SLA impact stated, 0.5 if acknowledged, 0.0 if missing"),
                ("symptom_description", "What customers actually experienced", 0.30,
                 "1.0 if customer-visible symptoms described, 0.0 if only internal view"),
            ]),
            pass_examples=["12,400 users saw 500 errors; 340 payment transactions failed ($48K GMV); 99.9% SLA breached for 3h47m"],
            fail_examples=["'There was a major outage affecting customers'"],
        ),
    ]

    return Rubric(
        task=task,
        domain="incident_management",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 12: Python Rate Limiter — Token Bucket with Redis Backend
# ============================================================================

def build_api_rate_limiter_rubric() -> Rubric:
    task = (
        "Design and implement a Python token-bucket rate limiter with sliding window support, "
        "Redis backend, distributed coordination, and graceful degradation when Redis is unavailable"
    )

    criteria = [
        Criterion(
            id="rl_algorithm",
            category="correctness",
            description="Token bucket algorithm is correctly implemented with sliding window",
            pass_condition="Proper token bucket: refill rate, bucket capacity, atomic consume. "
                          "Sliding window tracks requests in time window, not fixed buckets. "
                          "Handles burst vs sustained rate distinction.",
            scoring=_weighted(14, [
                ("token_bucket_correctness", "Refill logic, capacity, atomic consume are correct", 0.35,
                 "1.0 if mathematically correct token bucket, 0.5 if close, 0.0 if wrong"),
                ("sliding_window", "True sliding window, not fixed-window bucketing", 0.35,
                 "1.0 if sliding window, 0.5 if fixed window, 0.0 if no windowing"),
                ("burst_handling", "Distinguishes burst allowance from sustained rate", 0.30,
                 "1.0 if configurable burst vs sustained, 0.5 if implicit, 0.0 if not addressed"),
            ]),
            pass_examples=["Lua script for atomic check-and-decrement with ZRANGEBYSCORE for sliding window"],
            fail_examples=["Simple counter with fixed-minute reset"],
        ),
        Criterion(
            id="rl_redis_integration",
            category="infrastructure",
            description="Redis operations are atomic, efficient, and handle distributed coordination",
            pass_condition="Uses Lua scripts or MULTI/EXEC for atomicity. Proper key design with TTL. "
                          "Handles Redis cluster mode. Connection pooling.",
            scoring=_weighted(12, [
                ("atomicity", "Rate check + consume is atomic (Lua script or pipeline)", 0.40,
                 "1.0 if Lua script, 0.7 if pipeline, 0.3 if separate commands, 0.0 if race-prone"),
                ("key_design", "Key naming scheme with TTL prevents unbounded growth", 0.30,
                 "1.0 if namespaced keys with TTL, 0.5 if TTL only, 0.0 if no TTL"),
                ("connection_management", "Connection pooling, proper cleanup, cluster-aware", 0.30,
                 "1.0 if pool + cluster-aware, 0.5 if pool only, 0.0 if per-request connections"),
            ]),
            pass_examples=["Lua: local tokens = redis.call('GET', key); if tokens > 0 then redis.call('DECR', key) ..."],
            fail_examples=["GET then SET with race condition between calls"],
        ),
        Criterion(
            id="rl_degradation",
            category="resilience",
            description="Graceful degradation when Redis is unavailable — doesn't block requests",
            pass_condition="Falls back to in-memory rate limiting when Redis is down. "
                          "Circuit breaker pattern for Redis health. Configurable fail-open vs fail-closed. "
                          "Logs degradation state transitions.",
            scoring=_weighted(12, [
                ("fallback_mechanism", "In-memory fallback when Redis unreachable", 0.35,
                 "1.0 if local fallback with approximate rate limiting, 0.5 if fail-open only, 0.0 if crashes"),
                ("circuit_breaker", "Circuit breaker prevents hammering dead Redis", 0.30,
                 "1.0 if circuit breaker with half-open state, 0.5 if basic retry backoff, 0.0 if none"),
                ("configurability", "Fail-open vs fail-closed is configurable per use case", 0.35,
                 "1.0 if configurable with sensible default, 0.5 if hardcoded, 0.0 if not addressed"),
            ]),
            pass_examples=["CircuitBreaker(failure_threshold=5, recovery_timeout=30) wrapping Redis calls; fallback to local TokenBucket"],
            fail_examples=["try: redis.get() except: pass  # silently allow all traffic"],
        ),
        Criterion(
            id="rl_api_design",
            category="usability",
            description="Clean, well-typed API with decorator support and middleware integration",
            pass_condition="Type-annotated. Usable as decorator (@rate_limit) and as middleware. "
                          "Returns RateLimitResult with remaining/reset info. Async-compatible.",
            scoring=_weighted(10, [
                ("type_safety", "Full type hints, dataclasses for config and results", 0.30,
                 "1.0 if complete typing, 0.5 if partial, 0.0 if none"),
                ("decorator_support", "Usable as @rate_limit(rate='100/min') decorator", 0.30,
                 "1.0 if decorator with config, 0.5 if basic, 0.0 if only function call"),
                ("async_support", "Works with both sync and async code", 0.20,
                 "1.0 if async-native with sync wrapper, 0.5 if sync only, 0.0 if broken"),
                ("response_metadata", "Returns remaining tokens, reset time, retry-after", 0.20,
                 "1.0 if RateLimitResult with all metadata, 0.5 if partial, 0.0 if bool only"),
            ]),
            pass_examples=["@rate_limit(rate='100/min', burst=20, key=lambda req: req.client_ip)"],
            fail_examples=["def check(key): return True/False  # no metadata, no typing"],
        ),
        Criterion(
            id="rl_testing",
            category="quality",
            description="Includes meaningful test scenarios covering edge cases and distributed behavior",
            pass_condition="Test cases for: basic rate limiting, burst, window sliding, Redis failure fallback, "
                          "concurrent access, key isolation. At least 6 test scenarios.",
            scoring=_weighted(8, [
                ("coverage", "Tests cover happy path, edge cases, and failure modes", 0.50,
                 "% of key scenarios covered (basic, burst, window, failover, concurrent, isolation)"),
                ("concurrent_testing", "Tests verify behavior under concurrent access", 0.25,
                 "1.0 if concurrent test with assertions, 0.5 if mentioned, 0.0 if absent"),
                ("test_quality", "Tests are isolated, readable, use fixtures", 0.25,
                 "1.0 if pytest-style with fixtures, 0.5 if basic, 0.0 if untestable"),
            ]),
            pass_examples=["test_concurrent_requests_respect_limit(), test_redis_failover_uses_local_bucket()"],
            fail_examples=["No tests, or a single 'test_it_works' function"],
        ),
    ]

    return Rubric(
        task=task,
        domain="code_generation",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 13: Legal Contract Redline — SaaS Agreement
# ============================================================================

def build_legal_contract_redline_rubric() -> Rubric:
    task = (
        "Redline a cloud services SaaS agreement from the customer's perspective, identifying "
        "10 risky clauses and proposing specific alternative language with justification for each"
    )

    criteria = [
        Criterion(
            id="legal_clause_identification",
            category="analysis",
            description="Identifies genuinely risky clauses that matter to enterprise customers",
            pass_condition="10 distinct clauses identified. Covers: liability caps, indemnification, "
                          "data ownership, termination, SLA, IP assignment, audit rights, data portability, "
                          "governing law, and auto-renewal. Each risk is specific, not generic.",
            scoring=_weighted(14, [
                ("clause_count", "Exactly 10 distinct risky clauses identified", 0.20,
                 "1.0 if 10, 0.7 if 8-9, 0.5 if 6-7, 0.0 if <6"),
                ("risk_diversity", "Covers multiple risk categories (commercial, legal, technical, operational)", 0.35,
                 "1.0 if 4+ categories, 0.5 if 2-3, 0.0 if all same type"),
                ("risk_specificity", "Each risk is specific to the clause language, not generic boilerplate advice", 0.45,
                 "% of clauses with specific risk tied to actual contract language patterns"),
            ]),
            pass_examples=["'Clause 7.2 caps vendor liability at 12 months of fees — this is standard but should be uncapped for data breaches and IP infringement'"],
            fail_examples=["'The contract has risky terms' or listing generic legal concepts without clause references"],
        ),
        Criterion(
            id="legal_alternative_language",
            category="drafting",
            description="Proposed alternative language is legally precise and practically negotiable",
            pass_condition="Each of the 10 clauses has specific replacement language (not just 'change this'). "
                          "Language is contract-grade (not casual prose). Alternatives are commercially reasonable, "
                          "not one-sided wishlists.",
            scoring=_weighted(14, [
                ("specificity", "Actual replacement clause text, not just 'negotiate better terms'", 0.35,
                 "% of clauses with word-for-word replacement language"),
                ("legal_precision", "Language uses proper legal drafting conventions", 0.30,
                 "1.0 if contract-grade language, 0.5 if close, 0.0 if casual prose"),
                ("commercial_reasonableness", "Proposals a vendor would actually consider, not maximalist demands", 0.35,
                 "% of proposals that are commercially balanced rather than one-sided"),
            ]),
            pass_examples=["'Replace: \"Vendor's total liability shall not exceed fees paid in the preceding 12 months\" With: \"...shall not exceed 2x fees paid in the preceding 12 months, provided that this cap shall not apply to (i) breaches of Section X (Data Protection), (ii) indemnification obligations under Section Y...\"'"],
            fail_examples=["'Negotiate a higher liability cap' or 'Remove this clause entirely'"],
        ),
        Criterion(
            id="legal_justification",
            category="reasoning",
            description="Each redline includes business and legal justification, not just risk flagging",
            pass_condition="Each clause has: what the risk is, why it matters to the customer specifically, "
                          "what the market-standard position is, and what leverage the customer has.",
            scoring=_weighted(10, [
                ("risk_explanation", "Explains WHY the clause is risky, not just THAT it is", 0.35,
                 "% of clauses with specific risk scenario (not just 'this is risky')"),
                ("market_context", "References market-standard positions or benchmarks", 0.35,
                 "% of clauses with market-standard comparison"),
                ("negotiation_leverage", "Notes where customer has leverage and where to concede", 0.30,
                 "1.0 if prioritizes fights, 0.5 if treats all equally, 0.0 if no strategy"),
            ]),
            pass_examples=["'Uncapped liability for data breaches is market-standard in enterprise SaaS (cf. SOC 2 expectations). This is a high-leverage ask because...'"],
            fail_examples=["'This clause is unfavorable to the customer'"],
        ),
        Criterion(
            id="legal_organization",
            category="structure",
            description="Redline is organized by priority with clear formatting for legal review",
            pass_condition="Organized by priority (critical → important → nice-to-have). "
                          "Consistent format: clause reference, original text, proposed text, justification. "
                          "Executive summary at top.",
            scoring=_weighted(8, [
                ("prioritization", "Clauses ordered by risk severity with priority labels", 0.35,
                 "1.0 if tiered (critical/important/nice-to-have), 0.5 if ordered but unlabeled, 0.0 if random"),
                ("consistent_format", "Each redline follows same structure", 0.35,
                 "1.0 if all 10 follow identical format, 0.5 if mostly, 0.0 if inconsistent"),
                ("executive_summary", "Top-level summary of key risks and negotiation strategy", 0.30,
                 "1.0 if summary present, 0.0 if dives straight into clauses"),
            ]),
            pass_examples=["## Executive Summary\n3 critical, 4 important, 3 nice-to-have redlines...\n\n### Critical 1: Liability Cap (Section 7.2)\n**Current:** ... **Proposed:** ... **Justification:** ..."],
            fail_examples=["Unstructured list of complaints about the contract"],
        ),
    ]

    return Rubric(
        task=task,
        domain="legal_analysis",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 14: Airflow ETL DAG — Multi-Source with Schema Drift
# ============================================================================

def build_data_pipeline_dag_rubric() -> Rubric:
    task = (
        "Design an Airflow DAG (Python) for an ETL pipeline that ingests from 3 sources "
        "(REST API, S3 parquet, PostgreSQL), handles schema drift, implements idempotent "
        "upserts, and includes alerting and retry logic"
    )

    criteria = [
        Criterion(
            id="dag_structure",
            category="architecture",
            description="DAG is well-structured with proper task dependencies and separation of concerns",
            pass_condition="Separate extract, transform, load tasks per source. Proper dependency graph. "
                          "Uses TaskGroups or SubDAGs for source isolation. Sensor for data availability. "
                          "DAG-level config (schedule, catchup, tags).",
            scoring=_weighted(12, [
                ("task_granularity", "E/T/L separated per source, not monolithic", 0.30,
                 "1.0 if E/T/L per source, 0.5 if partially separated, 0.0 if one giant task"),
                ("dependency_graph", "Dependencies model actual data flow accurately", 0.35,
                 "1.0 if correct DAG with parallelism where possible, 0.5 if linear, 0.0 if wrong"),
                ("dag_configuration", "Schedule, catchup=False, tags, retries, pool configured", 0.35,
                 "% of config options set appropriately"),
            ]),
            pass_examples=["TaskGroup per source with extract >> transform >> load, then join >> quality_check"],
            fail_examples=["Single PythonOperator that does everything"],
        ),
        Criterion(
            id="dag_schema_drift",
            category="resilience",
            description="Handles schema drift without manual intervention",
            pass_condition="Detects new/removed/changed columns from source. Applies schema evolution "
                          "(add columns, type coercion). Alerts on breaking changes without crashing. "
                          "Stores schema history for audit.",
            scoring=_weighted(14, [
                ("detection", "Compares incoming schema against expected schema", 0.30,
                 "1.0 if schema comparison with diff, 0.5 if basic type checking, 0.0 if no detection"),
                ("evolution", "Auto-handles additive changes (new columns), alerts on breaking", 0.35,
                 "1.0 if auto-evolve + alert on breaking, 0.5 if one, 0.0 if crashes on drift"),
                ("schema_history", "Persists schema versions for audit trail", 0.15,
                 "1.0 if versioned schema store, 0.0 if not tracked"),
                ("type_coercion", "Handles type changes gracefully (string→int, nullable changes)", 0.20,
                 "1.0 if coercion with fallback, 0.5 if basic, 0.0 if crashes"),
            ]),
            pass_examples=["SchemaEvolver.evolve(current_schema, incoming_schema) → AddColumn migrations + Slack alert for type changes"],
            fail_examples=["Hardcoded column list that breaks when source adds a field"],
        ),
        Criterion(
            id="dag_idempotency",
            category="correctness",
            description="All operations are idempotent — safe to re-run without duplicates",
            pass_condition="Upserts (not insert-only). Deduplication by natural key. "
                          "Watermark-based incremental loads. Atomic write-and-swap for target tables.",
            scoring=_weighted(12, [
                ("upsert_pattern", "Uses UPSERT/MERGE, not blind INSERT", 0.35,
                 "1.0 if proper upsert with conflict resolution, 0.5 if delete+insert, 0.0 if insert only"),
                ("incremental_loads", "Watermark/timestamp-based incremental extraction", 0.30,
                 "1.0 if watermark with state tracking, 0.5 if date-parameterized, 0.0 if full reload"),
                ("deduplication", "Natural key deduplication with deterministic behavior", 0.35,
                 "1.0 if natural key dedup, 0.5 if row-level dedup, 0.0 if no dedup"),
            ]),
            pass_examples=["INSERT ... ON CONFLICT (source_id, source_system) DO UPDATE SET ... WHERE updated_at > EXCLUDED.updated_at"],
            fail_examples=["INSERT INTO target SELECT * FROM staging — duplicates on re-run"],
        ),
        Criterion(
            id="dag_error_handling",
            category="reliability",
            description="Comprehensive error handling with retries, alerting, and dead-letter patterns",
            pass_condition="Task-level retries with exponential backoff. Dead-letter table for failed records. "
                          "Slack/PagerDuty alerting on failure. SLA miss detection.",
            scoring=_weighted(10, [
                ("retry_strategy", "Exponential backoff with configurable max retries", 0.30,
                 "1.0 if exponential backoff, 0.5 if fixed retries, 0.0 if no retries"),
                ("dead_letter", "Failed records captured for later investigation, not dropped", 0.25,
                 "1.0 if dead-letter table with error context, 0.0 if records dropped silently"),
                ("alerting", "Failure callbacks to Slack/PagerDuty with context", 0.25,
                 "1.0 if on_failure_callback with rich context, 0.5 if basic email, 0.0 if silent"),
                ("sla_monitoring", "SLA miss detection for pipeline lateness", 0.20,
                 "1.0 if SLA configured with alert, 0.0 if not addressed"),
            ]),
            pass_examples=["default_args={'retries': 3, 'retry_delay': timedelta(minutes=5), 'retry_exponential_backoff': True, 'on_failure_callback': slack_alert}"],
            fail_examples=["No retries, no alerting, failed records silently dropped"],
        ),
        Criterion(
            id="dag_code_quality",
            category="quality",
            description="Production-grade Python code with proper configuration management",
            pass_condition="Configuration via Airflow Variables or YAML, not hardcoded. "
                          "Custom operators or well-structured helper modules. Type hints. "
                          "Connection management via Airflow hooks. Testable structure.",
            scoring=_weighted(8, [
                ("configuration", "Connections/credentials via Airflow hooks and Variables, not hardcoded", 0.35,
                 "1.0 if all config via hooks/Variables, 0.5 if mixed, 0.0 if hardcoded"),
                ("modularity", "Reusable operators or helper modules, not inline lambdas", 0.30,
                 "1.0 if custom operators/modules, 0.5 if functions, 0.0 if inline"),
                ("typing_and_docs", "Type hints and docstrings on key functions", 0.35,
                 "1.0 if typed + documented, 0.5 if partial, 0.0 if neither"),
            ]),
            pass_examples=["from dags.operators.schema_evolve import SchemaEvolveOperator; uses PostgresHook, S3Hook"],
            fail_examples=["Hardcoded connection strings, 300-line DAG file with no helpers"],
        ),
    ]

    return Rubric(
        task=task,
        domain="data_engineering",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 15: Board Deck Narrative — Series B Vertical SaaS
# ============================================================================

def build_board_deck_narrative_rubric() -> Rubric:
    task = (
        "Write the narrative script (speaker notes) for a 12-slide Series B board deck "
        "covering financials, product roadmap, competitive landscape, hiring plan, and key risks, "
        "for a $30M ARR vertical SaaS company"
    )

    criteria = [
        Criterion(
            id="bd_structure",
            category="organization",
            description="12 slides with clear narrative arc from performance → strategy → risks",
            pass_condition="Exactly 12 slides. Logical sequence: title, metrics/financials, product, "
                          "market/competitive, go-to-market, hiring, risks, ask/next steps. "
                          "Each slide has 3-5 sentences of speaker notes.",
            scoring=_weighted(10, [
                ("slide_count", "Exactly 12 slides with distinct topics", 0.25,
                 "1.0 if 12, 0.7 if 10-11, 0.5 if 8-9, 0.0 if <8"),
                ("narrative_arc", "Logical flow: performance → opportunity → plan → risks → ask", 0.40,
                 "1.0 if clear arc, 0.5 if sections present but poorly ordered, 0.0 if random"),
                ("notes_density", "Speaker notes are 3-5 sentences per slide, not too thin or bloated", 0.35,
                 "% of slides with appropriate density (3-5 sentences)"),
            ]),
            pass_examples=["Slide 1: Title/Agenda → Slide 2: KPI Dashboard → ... → Slide 11: Key Risks → Slide 12: Board Ask"],
            fail_examples=["8 slides, no risk section, speaker notes that are full paragraphs"],
        ),
        Criterion(
            id="bd_financial_literacy",
            category="content",
            description="Financial content reflects Series B SaaS literacy — correct metrics and benchmarks",
            pass_condition="Includes ARR, growth rate, NDR, gross margin, burn rate, runway, CAC/LTV, "
                          "payback period. Numbers are internally consistent and plausible for $30M ARR. "
                          "References relevant benchmarks (Bessemer, KeyBanc).",
            scoring=_weighted(14, [
                ("metric_coverage", "All key SaaS metrics present (ARR, NDR, GM, burn, CAC/LTV)", 0.30,
                 "% of required metrics covered"),
                ("internal_consistency", "Numbers don't contradict each other (e.g., burn vs runway vs headcount)", 0.35,
                 "1.0 if all consistent, 0.5 if minor inconsistencies, 0.0 if contradictions"),
                ("benchmark_awareness", "References industry benchmarks for $30M ARR stage", 0.35,
                 "1.0 if benchmarked against relevant data, 0.5 if generic, 0.0 if no context"),
            ]),
            pass_examples=["$30M ARR, 85% YoY growth (T2D3 pace), 125% NDR, 78% gross margin, 18-month runway at current burn of $2.5M/mo"],
            fail_examples=["$30M ARR with 95% gross margin, 200% NDR, and infinite runway — internally inconsistent"],
        ),
        Criterion(
            id="bd_competitive_depth",
            category="analysis",
            description="Competitive landscape shows genuine strategic thinking, not just a feature matrix",
            pass_condition="Identifies 3-5 competitors with honest positioning. Explains differentiation "
                          "in terms of market segments, not features. Addresses where competitors are winning "
                          "and company's strategic response.",
            scoring=_weighted(10, [
                ("competitor_depth", "3-5 competitors analyzed with real strategic insight", 0.35,
                 "1.0 if 3-5 with genuine analysis, 0.5 if surface-level, 0.0 if just names"),
                ("honest_positioning", "Acknowledges where competitors are strong, not just FUD", 0.35,
                 "1.0 if balanced, 0.5 if mostly self-serving, 0.0 if only weaknesses of others"),
                ("strategic_response", "Clear strategic response to competitive threats", 0.30,
                 "1.0 if specific moat/response per threat, 0.5 if generic, 0.0 if absent"),
            ]),
            pass_examples=["'Competitor X dominates mid-market with a self-serve motion. Our response: we win on enterprise where workflow complexity makes their generic tool insufficient.'"],
            fail_examples=["Feature comparison table showing we win every category"],
        ),
        Criterion(
            id="bd_risk_candor",
            category="judgment",
            description="Risk section is candid about real threats, not softball risks",
            pass_condition="At least 4 genuine risks. Includes both execution risks and market risks. "
                          "Each risk has a mitigation plan. Doesn't list only risks you've already solved.",
            scoring=_weighted(10, [
                ("risk_authenticity", "Risks are genuine threats a board member would worry about", 0.40,
                 "1.0 if board-level risks, 0.5 if mid-management concerns, 0.0 if softballs"),
                ("risk_diversity", "Mix of execution, market, competitive, and team risks", 0.30,
                 "1.0 if 3+ risk categories, 0.5 if 2, 0.0 if all same type"),
                ("mitigation_specificity", "Each risk has a specific mitigation, not 'we're monitoring this'", 0.30,
                 "% of risks with actionable mitigation plans"),
            ]),
            pass_examples=["'Risk: Key competitor raised $100M and is underpricing by 40% in our core segment. Mitigation: Accelerating product-led growth for SMB while doubling down on enterprise where price sensitivity is lower.'"],
            fail_examples=["'Risk: the economy might slow down. Mitigation: we'll keep an eye on it.'"],
        ),
        Criterion(
            id="bd_audience_calibration",
            category="tone",
            description="Tone and depth are calibrated for a board audience — strategic, not operational",
            pass_condition="CEO-level framing, not manager-level detail. Strategic choices explained, "
                          "not task lists. Data-backed assertions. Confident but not dismissive of challenges.",
            scoring=_penalty(8, {
                "too_operational": -2.0,
                "no_data_backing": -2.0,
                "defensive_tone": -1.5,
                "jargon_without_context": -1.5,
                "sycophantic_to_board": -1.5,
                "too_long_per_slide": -1.0,
            }),
            pass_examples=["'We chose to invest in enterprise over SMB this quarter because NDR is 140% vs 105%, and the CAC payback is 8 months vs 14.'"],
            fail_examples=["'The team has been working really hard on a lot of great features this quarter'"],
        ),
    ]

    return Rubric(
        task=task,
        domain="business_communication",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 16: STRIDE Threat Model — Mobile Banking App
# ============================================================================

def build_security_threat_model_rubric() -> Rubric:
    task = (
        "Produce a STRIDE threat model for a mobile banking app with biometric auth, "
        "P2P payments, and third-party integrations, including threat matrix, risk ratings, "
        "and prioritized mitigations"
    )

    criteria = [
        Criterion(
            id="tm_stride_coverage",
            category="methodology",
            description="All 6 STRIDE categories applied systematically to each component",
            pass_condition="Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, "
                          "Elevation of Privilege — each applied to biometric auth, P2P payments, "
                          "and third-party integrations. At least 15 distinct threats identified.",
            scoring=_weighted(14, [
                ("stride_completeness", "All 6 STRIDE categories addressed", 0.30,
                 "% of STRIDE categories with at least one threat (6/6 = 1.0)"),
                ("component_coverage", "Threats identified for all 3 major components", 0.30,
                 "1.0 if all 3 components analyzed, 0.5 if 2, 0.0 if 1"),
                ("threat_count", "At least 15 distinct, non-trivial threats", 0.20,
                 "1.0 if 15+, 0.7 if 10-14, 0.5 if 7-9, 0.0 if <7"),
                ("threat_specificity", "Threats are specific to this app, not generic security advice", 0.20,
                 "% of threats specific to mobile banking with biometric/P2P context"),
            ]),
            pass_examples=["Spoofing/Biometric: Presentation attack using 3D-printed fingerprint or photo replay against face recognition on devices without dedicated secure enclave"],
            fail_examples=["'Spoofing: attacker could impersonate a user' — generic, not specific to biometric/mobile"],
        ),
        Criterion(
            id="tm_risk_rating",
            category="analysis",
            description="Risk ratings use a consistent framework (DREAD, CVSS, or custom) with justification",
            pass_condition="Each threat has: likelihood, impact, and combined risk score. "
                          "Uses consistent rating framework. Justifies ratings, not arbitrary numbers.",
            scoring=_weighted(12, [
                ("framework_consistency", "Uses a named risk framework applied consistently", 0.30,
                 "1.0 if DREAD/CVSS/custom applied to all, 0.5 if inconsistent, 0.0 if no framework"),
                ("rating_justification", "Ratings justified with reasoning, not arbitrary", 0.35,
                 "% of threats with justified ratings (not just 'High')"),
                ("likelihood_impact_separation", "Separately assesses likelihood and impact", 0.35,
                 "1.0 if both dimensions, 0.5 if combined only, 0.0 if single rating"),
            ]),
            pass_examples=["Likelihood: Medium (requires physical device access + enrolled fingerprint bypass); Impact: Critical (full account takeover); Risk: High"],
            fail_examples=["Risk: High — no reasoning or framework"],
        ),
        Criterion(
            id="tm_mitigations",
            category="remediation",
            description="Mitigations are specific, prioritized, and technically feasible",
            pass_condition="Each threat has at least one mitigation. Mitigations are specific technical controls, "
                          "not vague advice. Prioritized by risk rating. Include defense-in-depth layers.",
            scoring=_weighted(12, [
                ("mitigation_specificity", "Specific technical controls, not generic advice", 0.35,
                 "% of mitigations that name specific technologies/patterns"),
                ("prioritization", "Mitigations ordered by risk, with implementation phases", 0.25,
                 "1.0 if phased implementation plan, 0.5 if prioritized list, 0.0 if unprioritized"),
                ("defense_in_depth", "Multiple layers of defense for critical threats", 0.25,
                 "1.0 if critical threats have 2+ mitigations, 0.5 if single layer, 0.0 if none"),
                ("feasibility", "Mitigations are implementable given mobile app constraints", 0.15,
                 "1.0 if all feasible, 0.5 if some unrealistic, 0.0 if impractical"),
            ]),
            pass_examples=["Mitigation: (1) Require liveness detection via 3D face mapping, (2) Bind biometric to device TEE, (3) Step-up to SMS OTP for transactions >$500"],
            fail_examples=["Mitigation: 'Use strong authentication' or 'Follow OWASP guidelines'"],
        ),
        Criterion(
            id="tm_threat_matrix",
            category="structure",
            description="Threat matrix is well-organized with clear cross-referencing",
            pass_condition="Matrix/table format with: threat ID, STRIDE category, component, description, "
                          "risk rating, mitigations. Sortable/filterable by category and priority.",
            scoring=_weighted(8, [
                ("tabular_format", "Clear matrix/table format, not just prose", 0.35,
                 "1.0 if proper table with consistent columns, 0.5 if semi-structured, 0.0 if prose only"),
                ("cross_referencing", "Threats linked to mitigations by ID", 0.30,
                 "1.0 if IDs cross-referenced, 0.5 if inline, 0.0 if disconnected"),
                ("executive_summary", "Summary of critical findings and top-priority actions", 0.35,
                 "1.0 if exec summary at top, 0.0 if missing"),
            ]),
            pass_examples=["| T-01 | Spoofing | Biometric Auth | Fingerprint replay attack | High | M-01, M-02 |"],
            fail_examples=["Unstructured list of security concerns"],
        ),
        Criterion(
            id="tm_domain_depth",
            category="expertise",
            description="Demonstrates deep knowledge of mobile banking security, not generic application security",
            pass_condition="References: PSD2/SCA requirements, mobile platform security (TEE, Keystore, Secure Enclave), "
                          "payment network rules, biometric standards (FIDO2), and regulatory requirements.",
            scoring=_weighted(10, [
                ("regulatory_awareness", "References PSD2, PCI-DSS, or relevant financial regulations", 0.30,
                 "1.0 if specific regulatory references, 0.5 if generic compliance mention, 0.0 if absent"),
                ("platform_specifics", "Addresses iOS/Android specific security controls (TEE, Keychain)", 0.35,
                 "1.0 if platform-specific controls, 0.5 if generic mobile, 0.0 if desktop-centric"),
                ("payment_standards", "References payment-specific standards (EMV, tokenization)", 0.35,
                 "1.0 if payment standards referenced, 0.5 if basic, 0.0 if no payment context"),
            ]),
            pass_examples=["'P2P payments must comply with PSD2 SCA requirements — biometric alone satisfies one factor (inherence), but we need a second factor for transactions over EUR 30'"],
            fail_examples=["Generic OWASP Mobile Top 10 without banking-specific context"],
        ),
    ]

    return Rubric(
        task=task,
        domain="security_analysis",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 17: Rust Concurrent LRU Cache
# ============================================================================

def build_rust_concurrent_cache_rubric() -> Rubric:
    task = (
        "Implement a thread-safe LRU cache in Rust with TTL expiry, bounded memory, and "
        "lock-free reads using Arc, RwLock, and background eviction, including comprehensive "
        "error handling"
    )

    criteria = [
        Criterion(
            id="rust_lru_correctness",
            category="algorithm",
            description="LRU eviction is correctly implemented with O(1) get/put",
            pass_condition="Uses HashMap + doubly-linked list for O(1) operations. "
                          "Eviction removes least-recently-used on capacity overflow. "
                          "Get promotes entry to most-recently-used.",
            scoring=_weighted(14, [
                ("data_structure", "HashMap + linked list or equivalent O(1) structure", 0.35,
                 "1.0 if O(1) get+put, 0.5 if O(log n), 0.0 if O(n) scan"),
                ("eviction_correctness", "LRU entry evicted when capacity exceeded", 0.35,
                 "1.0 if correct LRU eviction, 0.5 if FIFO, 0.0 if wrong/missing"),
                ("access_promotion", "Get operation promotes to most-recently-used", 0.30,
                 "1.0 if get promotes, 0.0 if get doesn't update order"),
            ]),
            pass_examples=["struct LruCache<K, V> { map: HashMap<K, *mut Node<K, V>>, head: *mut Node, tail: *mut Node }"],
            fail_examples=["Vec::remove(0) for eviction — O(n), not a real LRU"],
        ),
        Criterion(
            id="rust_concurrency",
            category="thread_safety",
            description="Thread safety is achieved with minimal lock contention",
            pass_condition="Uses Arc<RwLock<...>> for shared ownership. Reads don't block other reads. "
                          "Write lock scope is minimized. No deadlock potential. "
                          "Background eviction thread doesn't hold locks during cleanup.",
            scoring=_weighted(14, [
                ("rwlock_usage", "RwLock for read-heavy workloads, not Mutex", 0.30,
                 "1.0 if RwLock with concurrent reads, 0.5 if Mutex, 0.0 if no sync"),
                ("lock_granularity", "Lock held for minimum duration, no lock in I/O paths", 0.35,
                 "1.0 if fine-grained locking, 0.5 if coarse, 0.0 if lock held across operations"),
                ("deadlock_freedom", "No potential for deadlock (single lock order, no nested locks)", 0.35,
                 "1.0 if provably deadlock-free, 0.5 if likely safe, 0.0 if nested locks possible"),
            ]),
            pass_examples=["let value = { let guard = self.inner.read().unwrap(); guard.get(&key).cloned() }; // read lock released before return"],
            fail_examples=["Mutex::lock() held for entire get+update operation"],
        ),
        Criterion(
            id="rust_ttl_eviction",
            category="functionality",
            description="TTL expiry and background eviction are correctly implemented",
            pass_condition="Per-entry TTL with configurable default. Background thread or task for "
                          "periodic eviction. Lazy eviction on access (don't return expired entries). "
                          "Background thread is cancellable (graceful shutdown).",
            scoring=_weighted(12, [
                ("per_entry_ttl", "Each entry has its own expiry timestamp", 0.30,
                 "1.0 if per-entry TTL, 0.5 if global only, 0.0 if no TTL"),
                ("background_eviction", "Periodic background sweep removes expired entries", 0.30,
                 "1.0 if background thread with configurable interval, 0.5 if lazy only, 0.0 if none"),
                ("lazy_check", "Get returns None for expired entries even before background sweep", 0.20,
                 "1.0 if lazy expiry on read, 0.0 if returns expired entries"),
                ("graceful_shutdown", "Background thread can be stopped cleanly", 0.20,
                 "1.0 if cancellation token / drop impl, 0.5 if join handle, 0.0 if leaked thread"),
            ]),
            pass_examples=["spawn(move || { loop { sleep(interval); cache.evict_expired(); if shutdown.load(Relaxed) { break; } } })"],
            fail_examples=["No TTL support, or global TTL with no per-entry override"],
        ),
        Criterion(
            id="rust_error_handling",
            category="robustness",
            description="Comprehensive error handling using Rust idioms (Result, custom errors)",
            pass_condition="Custom error enum. No unwrap() in library code. Poisoned lock recovery. "
                          "Memory bound enforcement. Errors are descriptive and actionable.",
            scoring=_weighted(8, [
                ("error_types", "Custom error enum covering all failure modes", 0.35,
                 "1.0 if custom enum, 0.5 if string errors, 0.0 if panics"),
                ("no_unwrap", "No unwrap()/expect() in non-test code", 0.30,
                 "1.0 if all Results handled, 0.5 if few unwraps, 0.0 if unwrap-heavy"),
                ("poison_recovery", "Handles poisoned RwLock from panicked threads", 0.35,
                 "1.0 if recovers from poison, 0.5 if propagates, 0.0 if not addressed"),
            ]),
            pass_examples=["match self.inner.read() { Ok(guard) => ..., Err(poisoned) => { let guard = poisoned.into_inner(); ... } }"],
            fail_examples=["self.inner.read().unwrap() — panics on poisoned lock"],
        ),
        Criterion(
            id="rust_api_ergonomics",
            category="usability",
            description="API is idiomatic Rust with good documentation and generic type support",
            pass_condition="Generic over K: Hash + Eq and V: Clone. Builder pattern for configuration. "
                          "Implements standard traits (Debug, Drop). Doc comments with examples. "
                          "Bounded memory via size_of or count.",
            scoring=_weighted(8, [
                ("generics", "Generic over K and V with appropriate trait bounds", 0.30,
                 "1.0 if generic with bounds, 0.5 if specific types, 0.0 if String only"),
                ("builder", "Builder pattern for cache configuration", 0.25,
                 "1.0 if builder with fluent API, 0.5 if struct init, 0.0 if no config"),
                ("trait_impls", "Implements Debug, Drop (for cleanup), Send + Sync", 0.20,
                 "% of appropriate traits implemented"),
                ("documentation", "Doc comments with usage examples on pub items", 0.25,
                 "1.0 if doc examples, 0.5 if basic docs, 0.0 if undocumented"),
            ]),
            pass_examples=["LruCache::<String, Vec<u8>>::builder().capacity(1000).ttl(Duration::from_secs(300)).build()"],
            fail_examples=["LruCache::new() with no configuration options, no docs"],
        ),
    ]

    return Rubric(
        task=task,
        domain="systems_programming",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 18: Competitive Analysis Memo — AI Code Assistants
# ============================================================================

def build_comp_analysis_memo_rubric() -> Rubric:
    task = (
        "Write a competitive analysis memo comparing 4 AI code assistant tools (Cursor, GitHub Copilot, "
        "Cody, Windsurf) across 8 dimensions with a recommendation for a 200-person engineering org"
    )

    criteria = [
        Criterion(
            id="ca_framework",
            category="structure",
            description="Analysis framework has 8 clearly defined dimensions with consistent evaluation",
            pass_condition="8 distinct evaluation dimensions covering: code quality, IDE integration, "
                          "language support, privacy/security, pricing, team features, context understanding, "
                          "and customization. Each dimension applied consistently across all 4 tools.",
            scoring=_weighted(10, [
                ("dimension_count", "Exactly 8 distinct, non-overlapping dimensions", 0.25,
                 "1.0 if 8 distinct, 0.7 if 6-7, 0.5 if 4-5, 0.0 if <4"),
                ("dimension_quality", "Dimensions are decision-relevant for a 200-person org", 0.35,
                 "% of dimensions that matter at enterprise scale (security, admin, cost)"),
                ("consistent_application", "Each dimension evaluated for all 4 tools", 0.40,
                 "1.0 if complete 4x8 matrix, 0.5 if gaps, 0.0 if inconsistent"),
            ]),
            pass_examples=["Dimensions: (1) Code generation accuracy, (2) Context window utilization, (3) IDE ecosystem, (4) Security/privacy, (5) Pricing at scale, (6) Admin/governance, (7) Customization, (8) Roadmap/trajectory"],
            fail_examples=["3 vague categories like 'Features', 'Price', 'Quality'"],
        ),
        Criterion(
            id="ca_accuracy",
            category="content",
            description="Factual claims about products are accurate and current",
            pass_condition="Pricing, features, and limitations are factually correct for current versions. "
                          "Distinguishes between GA features and beta/preview. No outdated information. "
                          "Sources or basis for claims stated.",
            scoring=_weighted(14, [
                ("factual_accuracy", "Claims about each tool are verifiably correct", 0.40,
                 "% of factual claims that are accurate"),
                ("currency", "Information reflects current product state, not 6-month-old features", 0.30,
                 "1.0 if current, 0.5 if mostly current, 0.0 if outdated"),
                ("ga_vs_beta", "Distinguishes GA features from beta/preview/announced", 0.30,
                 "1.0 if clearly distinguished, 0.5 if sometimes, 0.0 if no distinction"),
            ]),
            pass_examples=["'Cursor Pro: $20/user/mo with 500 fast requests (GPT-4/Claude), unlimited slow requests. Business: $40/user/mo with admin controls, SSO.'"],
            fail_examples=["Outdated pricing or features that were announced but never shipped"],
        ),
        Criterion(
            id="ca_recommendation",
            category="judgment",
            description="Recommendation is defensible, acknowledges tradeoffs, and fits the stated context",
            pass_condition="Clear primary recommendation with rationale. Addresses why not the alternatives. "
                          "Considers the 200-person org context (security, admin, cost at scale). "
                          "Suggests evaluation/pilot approach.",
            scoring=_weighted(12, [
                ("clear_recommendation", "Unambiguous primary pick with specific rationale", 0.30,
                 "1.0 if clear pick with reasoning, 0.5 if hedged, 0.0 if 'it depends'"),
                ("tradeoff_honesty", "Acknowledges what you give up with the recommendation", 0.30,
                 "1.0 if explicit tradeoffs, 0.5 if mentioned, 0.0 if only positives"),
                ("context_fit", "Recommendation specifically addresses 200-person enterprise needs", 0.20,
                 "1.0 if enterprise-specific (SSO, admin, compliance), 0.5 if generic, 0.0 if individual-focused"),
                ("rollout_plan", "Suggests phased evaluation or pilot approach", 0.20,
                 "1.0 if phased rollout plan, 0.5 if basic suggestion, 0.0 if no rollout guidance"),
            ]),
            pass_examples=["'Recommend Cursor Business for primary adoption with a 30-day pilot across 3 teams. Key tradeoff: higher per-seat cost vs Copilot, justified by superior context understanding and agent capabilities.'"],
            fail_examples=["'All tools have pros and cons, so it depends on your needs'"],
        ),
        Criterion(
            id="ca_depth",
            category="analysis",
            description="Analysis goes beyond feature lists to strategic and workflow implications",
            pass_condition="Covers workflow impact (not just features), team dynamics, vendor risk, "
                          "and trajectory/roadmap considerations. Includes at least 2 second-order insights "
                          "that wouldn't be obvious from product pages.",
            scoring=_weighted(10, [
                ("beyond_features", "Discusses workflow impact, productivity gains, learning curve", 0.35,
                 "1.0 if workflow analysis, 0.5 if feature-focused, 0.0 if just feature list"),
                ("vendor_risk", "Considers vendor viability, lock-in, and strategic direction", 0.30,
                 "1.0 if vendor risk assessed, 0.5 if mentioned, 0.0 if absent"),
                ("second_order_insights", "At least 2 non-obvious insights (e.g., impact on code review culture)", 0.35,
                 "1.0 if 2+ genuine insights, 0.5 if 1, 0.0 if all obvious"),
            ]),
            pass_examples=["'Second-order effect: teams using Cursor's agent mode report 40% fewer WIP PRs because devs complete full features in one session, changing code review patterns.'"],
            fail_examples=["Feature comparison table with checkmarks"],
        ),
        Criterion(
            id="ca_formatting",
            category="presentation",
            description="Memo is executive-ready with summary, comparison table, and clear sections",
            pass_condition="Executive summary (1 paragraph). Comparison matrix/table. "
                          "Detailed analysis per dimension. Recommendation section. Appendix with methodology.",
            scoring=_weighted(6, [
                ("exec_summary", "1-paragraph executive summary with recommendation", 0.30,
                 "1.0 if clear summary, 0.0 if missing"),
                ("comparison_table", "At-a-glance comparison matrix", 0.35,
                 "1.0 if clear matrix, 0.5 if partial, 0.0 if no table"),
                ("section_organization", "Clear sections with headers, consistent structure", 0.35,
                 "1.0 if well-organized, 0.5 if mostly, 0.0 if disorganized"),
            ]),
            pass_examples=["Executive summary → Comparison matrix → Detailed analysis (8 dimensions) → Recommendation → Rollout plan → Appendix"],
            fail_examples=["Wall of prose with no structure"],
        ),
    ]

    return Rubric(
        task=task,
        domain="strategic_analysis",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 19: ML Experiment Report — Domain Fine-Tuning
# ============================================================================

def build_ml_experiment_report_rubric() -> Rubric:
    task = (
        "Write a reproducible ML experiment report for fine-tuning a language model on "
        "domain-specific data, covering dataset construction, training methodology, evaluation "
        "metrics, ablation results, and failure analysis"
    )

    criteria = [
        Criterion(
            id="ml_methodology",
            category="rigor",
            description="Training methodology is fully specified and reproducible",
            pass_condition="Specifies: base model, fine-tuning approach (full/LoRA/QLoRA), hyperparameters "
                          "(LR, batch size, epochs, warmup), hardware, training time, and framework. "
                          "Enough detail for reproduction.",
            scoring=_weighted(14, [
                ("completeness", "All training parameters specified (model, method, hyperparams, hardware)", 0.35,
                 "% of required training details specified"),
                ("method_justification", "Explains why this fine-tuning approach was chosen", 0.30,
                 "1.0 if justified vs alternatives, 0.5 if mentioned, 0.0 if just stated"),
                ("reproducibility", "Could someone reproduce this from the report alone?", 0.35,
                 "1.0 if fully reproducible, 0.5 if mostly, 0.0 if missing key details"),
            ]),
            pass_examples=["Base: Llama-3-8B, Method: QLoRA (r=64, alpha=128, target: q_proj,v_proj), LR: 2e-4 cosine, Batch: 8 (gradient accumulation 4), 3 epochs, A100 80GB x2, ~4.5 hours"],
            fail_examples=["'We fine-tuned a large language model on our data'"],
        ),
        Criterion(
            id="ml_dataset",
            category="data",
            description="Dataset construction is documented with quality controls and statistics",
            pass_condition="Source, size, splits (train/val/test), preprocessing steps, quality filters, "
                          "distribution analysis, contamination checks. Includes dataset statistics table.",
            scoring=_weighted(12, [
                ("construction", "Source data, collection method, preprocessing pipeline documented", 0.30,
                 "% of pipeline steps documented"),
                ("statistics", "Size, splits, distribution metrics, class balance", 0.30,
                 "1.0 if comprehensive stats, 0.5 if basic counts, 0.0 if none"),
                ("quality_controls", "Dedup, filtering, contamination checks described", 0.25,
                 "1.0 if quality pipeline, 0.5 if basic filters, 0.0 if no quality control"),
                ("contamination_check", "Checks for test set leakage into training data", 0.15,
                 "1.0 if explicit contamination check, 0.0 if not addressed"),
            ]),
            pass_examples=["12,400 examples (10K train / 1.2K val / 1.2K test), sourced from internal docs. Deduped via MinHash (3.2% removed). N-gram contamination check against test set: 0 matches."],
            fail_examples=["'We used our company's data for training'"],
        ),
        Criterion(
            id="ml_evaluation",
            category="measurement",
            description="Evaluation uses multiple metrics with proper baselines and statistical significance",
            pass_condition="Multiple metrics (not just loss). Task-specific evaluation (not just perplexity). "
                          "Comparison against base model and at least one other baseline. "
                          "Confidence intervals or significance tests.",
            scoring=_weighted(12, [
                ("metric_diversity", "Multiple relevant metrics (accuracy, F1, BLEU, human eval, etc.)", 0.30,
                 "1.0 if 3+ relevant metrics, 0.5 if 1-2, 0.0 if loss only"),
                ("baseline_comparison", "Results compared to base model + at least one other baseline", 0.30,
                 "1.0 if 2+ baselines, 0.5 if base model only, 0.0 if no comparison"),
                ("statistical_rigor", "Confidence intervals, multiple runs, or significance tests", 0.20,
                 "1.0 if CI or significance test, 0.5 if multiple runs, 0.0 if single run"),
                ("task_specific_eval", "Evaluation on downstream task, not just language modeling metrics", 0.20,
                 "1.0 if task-specific, 0.5 if mixed, 0.0 if perplexity only"),
            ]),
            pass_examples=["Domain QA accuracy: 78.3% (CI: 76.1-80.5) vs base model 52.1% vs GPT-4 71.4%. 3 runs, std dev reported."],
            fail_examples=["'The model achieved good performance' or just reporting training loss"],
        ),
        Criterion(
            id="ml_ablation",
            category="analysis",
            description="Ablation study isolates the contribution of key design decisions",
            pass_condition="At least 3 ablations (e.g., dataset size, LoRA rank, base model, data mix). "
                          "Each ablation changes one variable. Results in table format. "
                          "Conclusions drawn from ablation results.",
            scoring=_weighted(10, [
                ("ablation_count", "At least 3 meaningful ablations", 0.30,
                 "1.0 if 3+, 0.5 if 1-2, 0.0 if none"),
                ("controlled_variables", "Each ablation changes exactly one variable", 0.30,
                 "1.0 if controlled, 0.5 if mostly, 0.0 if confounded"),
                ("insights", "Ablation results lead to actionable conclusions", 0.40,
                 "1.0 if clear insights (e.g., 'LoRA r=64 matches full FT at 1/3 cost'), 0.0 if just numbers"),
            ]),
            pass_examples=["Ablation table: LoRA rank (16/32/64/128) → accuracy saturates at r=64, r=128 adds compute cost with no quality gain"],
            fail_examples=["No ablations, or ablating multiple variables simultaneously"],
        ),
        Criterion(
            id="ml_failure_analysis",
            category="honesty",
            description="Failure analysis identifies what doesn't work and why, with concrete examples",
            pass_condition="Identifies specific failure modes with examples. Categorizes failures "
                          "(hallucination, format, knowledge gap). Quantifies failure rates. "
                          "Proposes concrete next steps.",
            scoring=_weighted(8, [
                ("failure_identification", "Specific failure modes identified with examples", 0.35,
                 "1.0 if categorized failures with examples, 0.5 if mentioned, 0.0 if absent"),
                ("quantification", "Failure rates quantified (e.g., 12% hallucination rate on X)", 0.30,
                 "1.0 if quantified, 0.5 if qualitative, 0.0 if not addressed"),
                ("next_steps", "Concrete proposed improvements based on failure analysis", 0.35,
                 "1.0 if specific improvements tied to failures, 0.5 if generic, 0.0 if absent"),
            ]),
            pass_examples=["Failure mode 1: Hallucinated entity names in 12% of responses (23/192 test examples). Root cause: training data skew toward entity-heavy documents. Proposed fix: entity-masking augmentation."],
            fail_examples=["'The model sometimes makes mistakes' with no analysis"],
        ),
    ]

    return Rubric(
        task=task,
        domain="technical_writing",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 20: Terraform Multi-Environment AWS Deployment
# ============================================================================

def build_terraform_multi_env_rubric() -> Rubric:
    task = (
        "Write Terraform HCL for a production-grade AWS deployment with VPC, ECS Fargate, "
        "RDS, and ALB across dev/staging/prod environments using workspaces and modules, "
        "with least-privilege IAM"
    )

    criteria = [
        Criterion(
            id="tf_modularity",
            category="architecture",
            description="Infrastructure is decomposed into reusable, composable Terraform modules",
            pass_condition="Separate modules for VPC, ECS, RDS, ALB, IAM. Root module composes them. "
                          "Modules are parameterized via variables, not hardcoded. "
                          "Module outputs feed into dependent modules.",
            scoring=_weighted(12, [
                ("module_decomposition", "Separate modules for each infrastructure concern", 0.35,
                 "% of components in dedicated modules (VPC, ECS, RDS, ALB, IAM = 5)"),
                ("parameterization", "Modules use variables, not hardcoded values", 0.30,
                 "1.0 if fully parameterized, 0.5 if mixed, 0.0 if hardcoded"),
                ("module_composition", "Root module wires modules together via outputs/inputs", 0.35,
                 "1.0 if clean composition, 0.5 if some direct references, 0.0 if monolithic"),
            ]),
            pass_examples=["modules/vpc/, modules/ecs/, modules/rds/ — root main.tf: module \"vpc\" { source = \"./modules/vpc\" ... }"],
            fail_examples=["Single main.tf with 500 lines and no modules"],
        ),
        Criterion(
            id="tf_multi_env",
            category="operations",
            description="Dev/staging/prod environments are properly isolated with environment-specific config",
            pass_condition="Workspace-based or directory-based env separation. Environment-specific tfvars. "
                          "Resource naming includes environment. Different sizing per environment "
                          "(smaller instances in dev). State isolation.",
            scoring=_weighted(12, [
                ("env_separation", "Clear mechanism for env isolation (workspaces or directories)", 0.30,
                 "1.0 if workspaces with var files, 0.5 if basic separation, 0.0 if not separated"),
                ("config_differentiation", "Resource sizes/counts differ by environment", 0.30,
                 "1.0 if env-specific sizing (e.g., t3.micro in dev, r5.xlarge in prod), 0.5 if some, 0.0 if identical"),
                ("naming_convention", "Resources named with environment prefix/suffix", 0.20,
                 "1.0 if consistent naming, 0.5 if partial, 0.0 if no env in names"),
                ("state_isolation", "Separate state files per environment", 0.20,
                 "1.0 if isolated state (workspace or backend key), 0.0 if shared state"),
            ]),
            pass_examples=["terraform workspace select prod && terraform apply -var-file=envs/prod.tfvars"],
            fail_examples=["Same config for all environments, no workspace or var-file differentiation"],
        ),
        Criterion(
            id="tf_iam_security",
            category="security",
            description="IAM follows least-privilege with no wildcards in production policies",
            pass_condition="Task execution role with minimal permissions. No Action: '*' or Resource: '*'. "
                          "Service-linked roles where appropriate. Separate roles for ECS task vs execution. "
                          "Secrets in SSM/Secrets Manager, not environment variables.",
            scoring=_penalty(14, {
                "action_wildcard": -4.0,
                "resource_wildcard": -3.0,
                "combined_task_execution_role": -2.0,
                "hardcoded_secrets": -4.0,
                "no_secrets_management": -2.0,
                "overly_permissive_sg": -2.0,
                "admin_access_policy": -4.0,
            }),
            pass_examples=["aws_iam_role.ecs_task_role with policy allowing only s3:GetObject on specific bucket ARN"],
            fail_examples=["Action: ['*'], Resource: ['*'] — admin access on ECS task role"],
        ),
        Criterion(
            id="tf_networking",
            category="infrastructure",
            description="VPC and networking are production-grade with proper isolation and security groups",
            pass_condition="Multi-AZ VPC with public/private/data subnets. NAT Gateway for private subnet egress. "
                          "Security groups with specific rules (not 0.0.0.0/0 ingress). "
                          "ALB in public subnet, ECS in private, RDS in data subnet.",
            scoring=_weighted(10, [
                ("subnet_design", "Public/private/data subnets across multiple AZs", 0.30,
                 "1.0 if 3-tier multi-AZ, 0.5 if 2-tier, 0.0 if single subnet"),
                ("security_groups", "Specific ingress/egress rules, no 0.0.0.0/0 except ALB HTTP/S", 0.35,
                 "1.0 if specific rules, 0.5 if mostly specific, 0.0 if wide open"),
                ("tier_isolation", "ALB→public, ECS→private, RDS→data with proper routing", 0.35,
                 "1.0 if correct tier placement, 0.5 if partially correct, 0.0 if flat"),
            ]),
            pass_examples=["Private subnets for ECS with NAT GW egress; RDS in data subnets with SG allowing only ECS task SG ingress on 5432"],
            fail_examples=["Single public subnet for everything, 0.0.0.0/0 on all security groups"],
        ),
        Criterion(
            id="tf_best_practices",
            category="quality",
            description="Follows Terraform best practices: remote state, locking, tagging, outputs",
            pass_condition="Remote state backend (S3 + DynamoDB). Consistent tagging strategy. "
                          "terraform.tfvars for defaults. Outputs for important values. "
                          "Version constraints on providers and modules.",
            scoring=_weighted(8, [
                ("remote_state", "S3 backend with DynamoDB locking", 0.30,
                 "1.0 if S3+DynamoDB, 0.5 if S3 only, 0.0 if local state"),
                ("tagging", "Consistent tagging (Environment, Project, ManagedBy) on all resources", 0.25,
                 "1.0 if consistent tags, 0.5 if partial, 0.0 if none"),
                ("version_constraints", "Provider and module versions pinned", 0.25,
                 "1.0 if versions pinned, 0.5 if partial, 0.0 if unpinned"),
                ("outputs", "Key values (endpoints, ARNs) exposed as outputs", 0.20,
                 "1.0 if comprehensive outputs, 0.5 if some, 0.0 if none"),
            ]),
            pass_examples=["backend \"s3\" { bucket = \"tfstate-myproject\", dynamodb_table = \"tfstate-lock\", key = \"env/${terraform.workspace}\" }"],
            fail_examples=["Local state, no tagging, no version pins"],
        ),
    ]

    return Rubric(
        task=task,
        domain="infrastructure_as_code",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 21: Procurement Negotiation Playbook
# ============================================================================

def build_negotiation_playbook_rubric() -> Rubric:
    task = (
        "Create a procurement negotiation playbook for a $500K enterprise SaaS deal, including "
        "BATNA analysis, concession strategy, anchoring tactics, and scripted responses to "
        "5 common vendor objections"
    )

    criteria = [
        Criterion(
            id="neg_batna",
            category="strategy",
            description="BATNA analysis is thorough and quantified, not just 'we could walk away'",
            pass_condition="Identifies 2-3 specific alternatives with cost/capability comparison. "
                          "Quantifies switching costs. Defines reservation price and ZOPA. "
                          "Assesses vendor's BATNA as well.",
            scoring=_weighted(14, [
                ("alternative_depth", "2-3 specific named alternatives with cost estimates", 0.30,
                 "1.0 if 2-3 quantified alternatives, 0.5 if vague alternatives, 0.0 if just 'walk away'"),
                ("switching_cost", "Quantifies migration/switching costs for each alternative", 0.25,
                 "1.0 if $ estimates for switching, 0.5 if qualitative, 0.0 if not addressed"),
                ("reservation_price", "Clear reservation price derived from BATNA analysis", 0.20,
                 "1.0 if derived from analysis, 0.5 if stated without derivation, 0.0 if absent"),
                ("vendor_batna", "Estimates the vendor's BATNA and leverage", 0.25,
                 "1.0 if vendor's alternatives assessed, 0.5 if mentioned, 0.0 if one-sided"),
            ]),
            pass_examples=["BATNA: (1) Competitor X at $420K but needs $80K migration; (2) Build in-house at $350K first-year but $200K/yr maintenance; Reservation price: $480K"],
            fail_examples=["'If they don't give us a good price, we'll go with someone else'"],
        ),
        Criterion(
            id="neg_concession_strategy",
            category="tactics",
            description="Concession strategy is structured, not improvised — with clear give/get trades",
            pass_condition="Ranked list of concessions with estimated value to each side. "
                          "Linked trades (give X, get Y). Never concede without getting something back. "
                          "Starts with high-value-to-them, low-cost-to-us concessions.",
            scoring=_weighted(12, [
                ("concession_ranking", "Concessions ranked by value and cost", 0.30,
                 "1.0 if ranked matrix of give/get with values, 0.5 if list, 0.0 if ad hoc"),
                ("linked_trades", "Each concession is linked to a reciprocal ask", 0.30,
                 "% of concessions with explicit linked gets"),
                ("value_asymmetry", "Identifies concessions cheap for us but valuable to vendor", 0.25,
                 "1.0 if asymmetric value analysis, 0.5 if basic, 0.0 if not analyzed"),
                ("sequencing", "Clear order of concessions from least to most costly", 0.15,
                 "1.0 if sequenced, 0.0 if unordered"),
            ]),
            pass_examples=["Concession 1: Agree to 3-year term (low cost to us, high value to vendor for ARR predictability) → Get: 20% volume discount + quarterly billing"],
            fail_examples=["'We can offer a longer contract if needed'"],
        ),
        Criterion(
            id="neg_objection_scripts",
            category="execution",
            description="Scripted responses to 5 vendor objections are realistic and effective",
            pass_condition="5 common objections (price is firm, feature not available, competitor comparison, "
                          "implementation timeline, contract terms). Each has: verbatim vendor line, "
                          "why they say it, and 2-3 response options with different assertiveness levels.",
            scoring=_weighted(12, [
                ("objection_realism", "Objections are things vendors actually say in enterprise deals", 0.30,
                 "% of objections that are realistic vendor positions"),
                ("response_quality", "Responses address the underlying interest, not just the position", 0.35,
                 "% of responses that reframe using interest-based negotiation"),
                ("response_options", "Multiple response options per objection (soft/medium/firm)", 0.20,
                 "1.0 if 2-3 options per objection, 0.5 if single response, 0.0 if no scripts"),
                ("tactical_depth", "Responses use specific negotiation techniques (labeling, mirroring, anchoring)", 0.15,
                 "1.0 if named techniques, 0.5 if implicit, 0.0 if generic"),
            ]),
            pass_examples=["Objection: 'Our pricing is non-negotiable at this tier.' Response (medium): 'I understand the list price reflects your standard packaging. We're committed to your platform — what if we structured this as a 3-year agreement? That gives your team ARR predictability, and we'd need the economics to reflect that commitment.'"],
            fail_examples=["'If they say the price is firm, tell them we need a discount'"],
        ),
        Criterion(
            id="neg_anchoring",
            category="tactics",
            description="Anchoring strategy is specific with first-offer rationale and counteroffer preparation",
            pass_condition="Defines first offer with justification (benchmark, competitor pricing, ROI analysis). "
                          "Prepares for vendor's anchor with re-anchoring tactics. "
                          "Uses objective criteria to support anchor.",
            scoring=_weighted(8, [
                ("first_offer", "Specific first offer with data-backed justification", 0.40,
                 "1.0 if $ amount with rationale, 0.5 if vague range, 0.0 if no anchor"),
                ("counter_anchor", "Prepared response to vendor's opening anchor", 0.30,
                 "1.0 if re-anchoring strategy, 0.5 if basic counter, 0.0 if unprepared"),
                ("objective_criteria", "Anchored in market data, ROI, or benchmarks", 0.30,
                 "1.0 if data-backed, 0.5 if qualitative, 0.0 if arbitrary"),
            ]),
            pass_examples=["First offer: $375K (25% below list) anchored on: (1) G2 benchmark data showing 30% avg enterprise discount, (2) Competitor X quoted $400K for similar scope"],
            fail_examples=["'Start low and negotiate up'"],
        ),
        Criterion(
            id="neg_structure",
            category="usability",
            description="Playbook is structured for use during actual negotiation, not just pre-read",
            pass_condition="Quick-reference format. Decision tree for common scenarios. "
                          "Red lines clearly marked. Escalation criteria defined. "
                          "Summary card for negotiator to bring to the meeting.",
            scoring=_weighted(6, [
                ("quick_reference", "Summary card or cheat sheet for live use", 0.35,
                 "1.0 if one-page reference card, 0.5 if summary section, 0.0 if long-form only"),
                ("decision_tree", "If/then logic for common negotiation branches", 0.30,
                 "1.0 if decision tree or flowchart, 0.5 if scenarios listed, 0.0 if linear"),
                ("red_lines", "Non-negotiable terms clearly marked", 0.35,
                 "1.0 if red lines explicit, 0.0 if no boundaries defined"),
            ]),
            pass_examples=["## Red Lines (Do Not Cross)\n- No auto-renewal without 90-day notice clause\n- No unlimited liability for our data breach\n## Quick Reference Card\n..."],
            fail_examples=["10-page essay with no reference format for live use"],
        ),
    ]

    return Rubric(
        task=task,
        domain="business_strategy",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 22: Federated GraphQL Schema — E-Commerce Platform
# ============================================================================

def build_graphql_schema_federation_rubric() -> Rubric:
    task = (
        "Design a federated GraphQL schema for an e-commerce platform spanning 4 subgraphs "
        "(users, products, orders, payments) with proper entity resolution, auth directives, "
        "and N+1 prevention"
    )

    criteria = [
        Criterion(
            id="gql_subgraph_design",
            category="architecture",
            description="4 subgraphs with clear domain boundaries and proper entity ownership",
            pass_condition="Each subgraph owns its domain types. Entity references use @key directive. "
                          "No circular dependencies between subgraphs. Shared types handled via @shareable. "
                          "Each subgraph can be deployed independently.",
            scoring=_weighted(14, [
                ("domain_boundaries", "Each subgraph owns distinct types with no overlap", 0.30,
                 "% of types correctly owned by single subgraph"),
                ("entity_keys", "@key directives on all cross-subgraph entities", 0.35,
                 "1.0 if all entities have @key, 0.5 if most, 0.0 if missing"),
                ("independence", "Subgraphs can be deployed independently without breaking others", 0.35,
                 "1.0 if independent deployment possible, 0.5 if mostly, 0.0 if tightly coupled"),
            ]),
            pass_examples=["type User @key(fields: \"id\") in users subgraph; type Order @key(fields: \"id\") extends User @external in orders subgraph"],
            fail_examples=["All types in one schema, or circular type ownership"],
        ),
        Criterion(
            id="gql_entity_resolution",
            category="correctness",
            description="Entity resolution and reference resolvers are correctly defined across subgraphs",
            pass_condition="__resolveReference implementations for all extended types. "
                          "Proper @external and @requires annotations. "
                          "Handles entity not found (null vs error). Batch resolution for performance.",
            scoring=_weighted(12, [
                ("resolve_reference", "__resolveReference defined for all cross-subgraph entities", 0.30,
                 "% of extended entities with resolvers"),
                ("external_requires", "Correct use of @external and @requires for computed fields", 0.30,
                 "1.0 if correct annotations, 0.5 if partial, 0.0 if missing"),
                ("error_handling", "Entity not found returns null or typed error, not crash", 0.20,
                 "1.0 if handled, 0.0 if unhandled"),
                ("batch_resolution", "Batch/dataloader pattern for entity resolution", 0.20,
                 "1.0 if batched, 0.5 if individual, 0.0 if not addressed"),
            ]),
            pass_examples=["__resolveReference({ id }) => dataLoader.load(id) — batches entity lookups"],
            fail_examples=["No __resolveReference, or individual DB queries per entity"],
        ),
        Criterion(
            id="gql_auth",
            category="security",
            description="Auth directives provide field-level access control across subgraphs",
            pass_condition="Custom @auth or @requiresAuth directive with role-based access. "
                          "Applied at both type and field level. Gateway-level auth propagation. "
                          "Handles unauthenticated access gracefully.",
            scoring=_weighted(10, [
                ("directive_design", "Custom auth directive with role support", 0.35,
                 "1.0 if custom directive with roles, 0.5 if basic auth check, 0.0 if no auth"),
                ("field_level", "Auth applied at field level, not just type level", 0.30,
                 "1.0 if field-level (e.g., email only for ADMIN), 0.5 if type-level only, 0.0 if none"),
                ("propagation", "Auth context propagated from gateway to subgraphs", 0.35,
                 "1.0 if context propagation documented, 0.5 if implicit, 0.0 if not addressed"),
            ]),
            pass_examples=["directive @auth(requires: Role = USER) on FIELD_DEFINITION; type User { email: String @auth(requires: ADMIN) }"],
            fail_examples=["No auth directives, or only at the resolver level with no schema visibility"],
        ),
        Criterion(
            id="gql_n_plus_one",
            category="performance",
            description="N+1 prevention strategy is comprehensive — DataLoader, query planning, caching",
            pass_condition="DataLoader pattern for all entity resolution. @defer for expensive fields. "
                          "Query plan analysis showing batch optimization. Caching strategy for hot entities. "
                          "Pagination on all list fields.",
            scoring=_weighted(10, [
                ("dataloader", "DataLoader pattern used for all cross-subgraph fetches", 0.35,
                 "1.0 if DataLoader everywhere, 0.5 if some, 0.0 if none"),
                ("pagination", "All list fields use connection/pagination pattern", 0.25,
                 "1.0 if Relay-style connections, 0.5 if basic limit/offset, 0.0 if unbounded lists"),
                ("caching", "Caching strategy for frequently accessed entities", 0.20,
                 "1.0 if cache strategy documented, 0.5 if mentioned, 0.0 if absent"),
                ("query_complexity", "Query complexity/depth limiting to prevent abuse", 0.20,
                 "1.0 if complexity limits, 0.5 if depth limit, 0.0 if unbounded"),
            ]),
            pass_examples=["orders(first: 20, after: cursor): OrderConnection! — with DataLoader for user resolution, Redis cache for product lookups"],
            fail_examples=["orders: [Order!]! — unbounded list with N+1 user queries"],
        ),
        Criterion(
            id="gql_schema_quality",
            category="design",
            description="Schema follows GraphQL best practices: naming, nullability, input types, errors",
            pass_condition="Consistent naming conventions. Proper nullability (nullable by default, ! where guaranteed). "
                          "Input types for mutations. Union/interface for polymorphic types. "
                          "Typed errors, not string messages.",
            scoring=_weighted(8, [
                ("naming", "Consistent PascalCase types, camelCase fields, SCREAMING_SNAKE enums", 0.25,
                 "1.0 if consistent, 0.5 if mostly, 0.0 if inconsistent"),
                ("nullability", "Intentional nullability — not everything is non-null", 0.25,
                 "1.0 if thoughtful nullability, 0.5 if all non-null or all nullable, 0.0 if inconsistent"),
                ("input_types", "Mutations use dedicated input types, not inline args", 0.25,
                 "1.0 if input types for mutations, 0.5 if mixed, 0.0 if inline args only"),
                ("error_handling", "Typed errors via unions or result types, not just strings", 0.25,
                 "1.0 if union PaymentResult = Payment | PaymentError, 0.5 if error extensions, 0.0 if string messages"),
            ]),
            pass_examples=["mutation createOrder(input: CreateOrderInput!): CreateOrderResult! where union CreateOrderResult = Order | InsufficientStockError | PaymentFailedError"],
            fail_examples=["mutation createOrder(productId: ID!, quantity: Int!): Order! — no input type, no error type"],
        ),
    ]

    return Rubric(
        task=task,
        domain="api_design",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 23: SOC 2 Type II Gap Analysis
# ============================================================================

def build_regulatory_gap_analysis_rubric() -> Rubric:
    task = (
        "Perform a SOC 2 Type II readiness gap analysis for a 50-person B2B SaaS startup, "
        "identifying control gaps across all 5 trust service criteria with remediation "
        "priorities and estimated timelines"
    )

    criteria = [
        Criterion(
            id="soc2_tsc_coverage",
            category="completeness",
            description="All 5 Trust Service Criteria systematically assessed",
            pass_condition="Security, Availability, Processing Integrity, Confidentiality, and Privacy — "
                          "each with specific control objectives evaluated. References actual AICPA "
                          "criteria (CC1–CC9 series).",
            scoring=_weighted(14, [
                ("tsc_coverage", "All 5 TSC categories addressed with specific controls", 0.35,
                 "% of TSC categories with detailed control assessment (5/5 = 1.0)"),
                ("criteria_references", "References specific CC criteria (CC1.1, CC6.1, etc.)", 0.30,
                 "1.0 if specific criteria referenced, 0.5 if category-level, 0.0 if generic"),
                ("control_depth", "Each TSC has 3+ specific controls evaluated", 0.35,
                 "1.0 if 3+ controls per TSC, 0.5 if 1-2, 0.0 if surface-level"),
            ]),
            pass_examples=["CC6.1 (Logical Access): Current state — SSO via Google Workspace, no MFA enforced for CLI/API access. Gap: MFA not required for all access paths."],
            fail_examples=["'Security: needs improvement. Availability: mostly good.' — no specific controls"],
        ),
        Criterion(
            id="soc2_gap_specificity",
            category="analysis",
            description="Gaps are specific to a 50-person startup context, not generic compliance advice",
            pass_condition="Gaps reflect startup reality: limited security team, rapid deployment, "
                          "shared infrastructure, informal processes. At least 12 specific gaps identified. "
                          "Each gap states current state vs required state.",
            scoring=_weighted(12, [
                ("startup_context", "Gaps reflect realistic startup gaps (no CISO, shared accounts, etc.)", 0.35,
                 "% of gaps that are realistic for a 50-person startup"),
                ("current_vs_required", "Each gap states 'what is' vs 'what should be'", 0.30,
                 "% of gaps with explicit current/required comparison"),
                ("gap_count", "At least 12 specific, non-trivial gaps identified", 0.20,
                 "1.0 if 12+, 0.7 if 8-11, 0.5 if 5-7, 0.0 if <5"),
                ("evidence_basis", "Gaps based on observable evidence, not assumptions", 0.15,
                 "1.0 if evidence-based, 0.5 if reasonable assumptions, 0.0 if generic"),
            ]),
            pass_examples=["Gap: No formal change management process — developers deploy to production via direct git push to main. Required: Documented change management with approval workflow, testing requirements, and rollback procedures (CC8.1)."],
            fail_examples=["'The company needs better security controls' — no specifics"],
        ),
        Criterion(
            id="soc2_remediation",
            category="planning",
            description="Remediation plan is prioritized, resource-aware, and has realistic timelines",
            pass_condition="Gaps prioritized by audit risk and effort. Each remediation has: specific action, "
                          "responsible role, estimated effort (person-weeks), timeline, and dependencies. "
                          "Total timeline realistic for a startup (3-6 months, not 2 years).",
            scoring=_weighted(12, [
                ("prioritization", "Remediation prioritized by audit risk (not just effort)", 0.30,
                 "1.0 if risk-based priority, 0.5 if effort-based, 0.0 if unprioritized"),
                ("actionability", "Each remediation is a specific deliverable with responsible party", 0.30,
                 "% of remediations with specific action + owner"),
                ("timeline_realism", "Total timeline is realistic for a 50-person startup", 0.20,
                 "1.0 if 3-6 months, 0.5 if 6-12 months, 0.0 if unrealistic"),
                ("resource_awareness", "Acknowledges limited security team and suggests pragmatic approaches", 0.20,
                 "1.0 if pragmatic (e.g., 'use managed service X instead of building'), 0.5 if aware, 0.0 if enterprise-scale"),
            ]),
            pass_examples=["Priority 1 (Week 1-2): Enforce MFA via Google Workspace admin settings — 2 hours effort, IT lead. Unblocks all access control controls."],
            fail_examples=["'Implement a comprehensive security program' — no timeline, no specifics"],
        ),
        Criterion(
            id="soc2_tooling",
            category="practicality",
            description="Recommends specific tools and platforms appropriate for startup scale",
            pass_condition="Names specific compliance platforms (Vanta, Drata, Secureframe). "
                          "Recommends specific technical controls (not just 'use encryption'). "
                          "Suggests automation where possible. Cost-conscious.",
            scoring=_weighted(8, [
                ("platform_recommendation", "Names specific compliance automation platform", 0.30,
                 "1.0 if specific platform with reasoning, 0.5 if category, 0.0 if none"),
                ("technical_controls", "Specific tool/service recommendations per gap", 0.35,
                 "% of gaps with named tool/service recommendation"),
                ("cost_awareness", "Considers startup budget constraints in recommendations", 0.35,
                 "1.0 if cost-conscious (free tier, startup programs), 0.5 if mentioned, 0.0 if enterprise pricing"),
            ]),
            pass_examples=["Use Vanta ($15K/yr startup plan) for continuous compliance monitoring. For endpoint management, deploy Fleet (open source) rather than Jamf ($50K+ enterprise)."],
            fail_examples=["'Implement a SIEM solution' — no specific product, no cost consideration"],
        ),
        Criterion(
            id="soc2_audit_readiness",
            category="judgment",
            description="Includes practical audit preparation guidance beyond just fixing gaps",
            pass_condition="Policy templates needed. Evidence collection strategy. Auditor selection advice. "
                          "Type I vs Type II sequencing recommendation. Observation period planning.",
            scoring=_weighted(6, [
                ("policy_guidance", "Lists specific policies needed with templates or outlines", 0.35,
                 "1.0 if policy list with scope/content guidance, 0.5 if list only, 0.0 if absent"),
                ("evidence_strategy", "How to collect and organize evidence during observation period", 0.30,
                 "1.0 if evidence collection plan, 0.5 if mentioned, 0.0 if absent"),
                ("audit_sequencing", "Type I → Type II recommendation with timing", 0.35,
                 "1.0 if sequencing advice, 0.0 if not addressed"),
            ]),
            pass_examples=["Recommended path: 3 months remediation → Type I audit (1 month) → 6-month observation period → Type II. Start evidence collection from Day 1 of remediation."],
            fail_examples=["No audit process guidance, just gap list"],
        ),
    ]

    return Rubric(
        task=task,
        domain="compliance",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 24: Debugging Walkthrough — Node.js Race Condition
# ============================================================================

def build_debugging_walkthrough_rubric() -> Rubric:
    task = (
        "Write a step-by-step debugging walkthrough for a race condition in a Node.js Express "
        "app where concurrent requests to a shared PostgreSQL connection pool cause intermittent "
        "500 errors under load"
    )

    criteria = [
        Criterion(
            id="dbg_reproduction",
            category="diagnosis",
            description="Provides a clear, minimal reproduction of the race condition",
            pass_condition="Shows the vulnerable code pattern. Explains why it's intermittent. "
                          "Provides a load test command or script to trigger the bug reliably. "
                          "Identifies the exact window where the race occurs.",
            scoring=_weighted(14, [
                ("vulnerable_code", "Shows a realistic code pattern that exhibits the race condition", 0.30,
                 "1.0 if realistic vulnerable code, 0.5 if abstract, 0.0 if no code"),
                ("race_window", "Explains the exact timing window where the race occurs", 0.35,
                 "1.0 if precise window identified (e.g., between pool.query() and release), 0.5 if general, 0.0 if vague"),
                ("reproduction_method", "Provides a way to trigger the bug reliably", 0.35,
                 "1.0 if load test script/command, 0.5 if manual steps, 0.0 if 'just send lots of requests'"),
            ]),
            pass_examples=["autocannon -c 100 -d 10 http://localhost:3000/api/transfer — triggers pool exhaustion in ~3 seconds when pool.max is 10"],
            fail_examples=["'Sometimes under load you might see 500 errors'"],
        ),
        Criterion(
            id="dbg_root_cause",
            category="analysis",
            description="Root cause analysis correctly identifies the concurrency mechanism causing the bug",
            pass_condition="Identifies specific mechanism: connection pool exhaustion, connection leak, "
                          "transaction isolation violation, or shared mutable state. Shows the event loop "
                          "execution order that leads to the bug.",
            scoring=_weighted(14, [
                ("mechanism_identification", "Correctly identifies the concurrency mechanism", 0.35,
                 "1.0 if precise mechanism (pool leak, isolation violation), 0.5 if close, 0.0 if wrong"),
                ("event_loop_reasoning", "Shows how Node.js event loop scheduling creates the race", 0.35,
                 "1.0 if event loop order demonstrated, 0.5 if mentioned, 0.0 if ignored"),
                ("state_analysis", "Identifies what shared state is being corrupted or exhausted", 0.30,
                 "1.0 if specific state identified, 0.5 if general, 0.0 if not analyzed"),
            ]),
            pass_examples=["Connection acquired in handler A, awaits external API. Handler B acquires another connection. Pool exhausted at 10. Handler C awaits pool.connect() → timeout → 500. Root: connections not released on error paths."],
            fail_examples=["'Too many concurrent requests cause the server to crash'"],
        ),
        Criterion(
            id="dbg_fix",
            category="solution",
            description="Fix is correct, addresses the root cause, and doesn't introduce new issues",
            pass_condition="Shows before/after code. Fix addresses root cause (not just symptoms). "
                          "Uses proper patterns (try/finally for connection release, pool.query shorthand, "
                          "or serialized access). Includes connection leak prevention.",
            scoring=_weighted(12, [
                ("correctness", "Fix eliminates the race condition", 0.35,
                 "1.0 if race eliminated, 0.5 if mitigated, 0.0 if wrong fix"),
                ("root_cause_addressed", "Fix targets root cause, not symptoms (not just more connections)", 0.30,
                 "1.0 if root cause fixed, 0.5 if symptom treated, 0.0 if bandaid"),
                ("before_after", "Clear before/after code comparison", 0.20,
                 "1.0 if before/after, 0.5 if fix only, 0.0 if prose only"),
                ("no_regression", "Fix doesn't introduce new problems (deadlocks, performance)", 0.15,
                 "1.0 if considered, 0.5 if partially, 0.0 if not addressed"),
            ]),
            pass_examples=["Before: const client = await pool.connect(); await query(); await query2(); client.release(); // release skipped if query2 throws. After: try { ... } finally { client.release(); } — or better: pool.query() for single-query handlers"],
            fail_examples=["'Increase the pool size to 100' — treats symptom, not cause"],
        ),
        Criterion(
            id="dbg_methodology",
            category="process",
            description="Debugging methodology is systematic and teaches transferable techniques",
            pass_condition="Step-by-step process: observe → hypothesize → instrument → verify → fix → validate. "
                          "Shows specific debugging tools (pg_stat_activity, pool events, async_hooks). "
                          "Each step builds on the previous one logically.",
            scoring=_weighted(8, [
                ("systematic", "Follows a logical debugging sequence, not random poking", 0.35,
                 "1.0 if structured methodology, 0.5 if semi-structured, 0.0 if ad hoc"),
                ("tooling", "Uses specific debugging tools for the Node.js/PostgreSQL stack", 0.35,
                 "1.0 if names specific tools (pg_stat_activity, pool.on('acquire'), clinic.js), 0.5 if generic, 0.0 if none"),
                ("transferable", "Teaches principles applicable to other race conditions", 0.30,
                 "1.0 if generalizable lessons, 0.5 if task-specific only, 0.0 if not addressed"),
            ]),
            pass_examples=["Step 1: Check pg_stat_activity for idle connections → Step 2: pool.on('acquire'/'release') logging → Step 3: Correlate with request traces → Step 4: Identify unreleased connections"],
            fail_examples=["'Look at the code until you find the bug'"],
        ),
        Criterion(
            id="dbg_prevention",
            category="robustness",
            description="Includes prevention measures to avoid similar race conditions in the future",
            pass_condition="Recommends: connection pool monitoring, lint rules for connection management, "
                          "load testing in CI, circuit breaker patterns, and code review checklist items.",
            scoring=_weighted(8, [
                ("monitoring", "Pool monitoring with alerts for connection leaks", 0.30,
                 "1.0 if specific monitoring (pool size, wait time metrics), 0.5 if generic, 0.0 if absent"),
                ("code_patterns", "Recommends safe patterns (pool.query, try/finally, middleware)", 0.35,
                 "1.0 if safe patterns with code examples, 0.5 if mentioned, 0.0 if absent"),
                ("ci_integration", "Load testing or race condition detection in CI", 0.35,
                 "1.0 if CI integration, 0.5 if manual testing, 0.0 if not addressed"),
            ]),
            pass_examples=["Add pool.on('remove') logging + Prometheus gauge for pool.waitingCount. CI: autocannon smoke test on /healthz that fails if p99 > 500ms."],
            fail_examples=["'Be careful with concurrent code' — no actionable prevention"],
        ),
    ]

    return Rubric(
        task=task,
        domain="debugging",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Task 25: System Design Doc — Real-Time Collaborative Editor
# ============================================================================

def build_system_design_doc_rubric() -> Rubric:
    task = (
        "Write a system design document for a real-time collaborative document editor "
        "supporting 100K concurrent users, covering CRDT vs OT tradeoffs, conflict resolution, "
        "persistence layer, and operational concerns"
    )

    criteria = [
        Criterion(
            id="sd_crdt_ot",
            category="technical_depth",
            description="CRDT vs OT analysis is technically accurate with clear tradeoff reasoning",
            pass_condition="Correctly explains both approaches. Compares: convergence guarantees, "
                          "intent preservation, tombstone overhead, operational complexity. "
                          "Makes a justified choice for this system. Mentions specific algorithms "
                          "(Yjs/Automerge for CRDT, Jupiter/Google Wave OT).",
            scoring=_weighted(14, [
                ("technical_accuracy", "Both CRDT and OT correctly explained at algorithmic level", 0.35,
                 "1.0 if algorithmically correct, 0.5 if conceptually right, 0.0 if errors"),
                ("tradeoff_analysis", "Compares on multiple dimensions with clear reasoning", 0.30,
                 "1.0 if multi-dimensional comparison, 0.5 if surface-level, 0.0 if one-sided"),
                ("justified_choice", "Clear recommendation with rationale tied to requirements", 0.20,
                 "1.0 if justified choice, 0.5 if stated preference, 0.0 if no recommendation"),
                ("algorithm_specifics", "Names specific algorithms/libraries (Yjs, Automerge, Jupiter)", 0.15,
                 "1.0 if specific algorithms, 0.5 if general approach, 0.0 if abstract only"),
            ]),
            pass_examples=["CRDT (Yjs YATA algorithm) chosen over OT: no central server for transform, better offline support. Tradeoff: tombstone garbage collection needed, metadata overhead ~30% for active documents."],
            fail_examples=["'CRDTs are better than OT because they're newer' — no technical analysis"],
        ),
        Criterion(
            id="sd_architecture",
            category="design",
            description="System architecture supports 100K concurrent users with clear component diagram",
            pass_condition="Architecture with: WebSocket gateway, document service, storage layer, "
                          "presence service, auth layer. Horizontal scaling strategy. "
                          "Component interaction diagram or description. Load distribution strategy.",
            scoring=_weighted(12, [
                ("component_design", "All required components identified with clear responsibilities", 0.30,
                 "% of required components (gateway, doc service, storage, presence, auth)"),
                ("scaling_strategy", "Horizontal scaling with sharding/partitioning for 100K users", 0.35,
                 "1.0 if sharding strategy per document/user, 0.5 if generic 'add more servers', 0.0 if not addressed"),
                ("interaction_model", "Clear component interaction (sync vs async, protocols)", 0.35,
                 "1.0 if interaction diagram + protocol description, 0.5 if partial, 0.0 if unclear"),
            ]),
            pass_examples=["Documents partitioned by doc_id hash across N document servers. WebSocket gateway routes connections to correct partition. Presence broadcast via Redis pub/sub."],
            fail_examples=["'Use microservices and a load balancer' — no specific design"],
        ),
        Criterion(
            id="sd_conflict_resolution",
            category="correctness",
            description="Conflict resolution handles all edge cases: concurrent edits, offline, and reconnection",
            pass_condition="Handles: simultaneous edits to same position, offline edit merging, "
                          "client reconnection with state sync, undo/redo in collaborative context. "
                          "Describes merge semantics for different operation types (insert, delete, format).",
            scoring=_weighted(12, [
                ("concurrent_edits", "Handles simultaneous edits with deterministic merge", 0.30,
                 "1.0 if deterministic merge described, 0.5 if mentioned, 0.0 if not addressed"),
                ("offline_support", "Offline edits can be merged on reconnection", 0.30,
                 "1.0 if offline merge strategy, 0.5 if acknowledged, 0.0 if ignored"),
                ("operation_types", "Merge semantics differ by operation type (insert vs delete vs format)", 0.25,
                 "1.0 if operation-specific semantics, 0.5 if generic, 0.0 if one-size-fits-all"),
                ("undo_redo", "Collaborative undo that doesn't undo other users' changes", 0.15,
                 "1.0 if selective undo described, 0.5 if acknowledged, 0.0 if ignored"),
            ]),
            pass_examples=["Concurrent inserts at same position: use client_id as tiebreaker for deterministic ordering. Offline: client accumulates ops, on reconnect sends vector clock + pending ops, server rebases."],
            fail_examples=["'Last write wins' — no real conflict resolution"],
        ),
        Criterion(
            id="sd_persistence",
            category="storage",
            description="Persistence layer handles document storage, versioning, and crash recovery",
            pass_condition="Describes: document format (ops log vs snapshots), compaction strategy, "
                          "write-ahead logging for crash recovery, versioning for history/undo, "
                          "and snapshot frequency tradeoffs.",
            scoring=_weighted(10, [
                ("storage_model", "Clear model: ops log, snapshots, or hybrid with rationale", 0.30,
                 "1.0 if hybrid with rationale, 0.5 if single approach, 0.0 if not specified"),
                ("compaction", "Strategy for compacting operation log to prevent unbounded growth", 0.25,
                 "1.0 if compaction/snapshot strategy, 0.5 if acknowledged, 0.0 if ignored"),
                ("crash_recovery", "WAL or equivalent for crash recovery without data loss", 0.25,
                 "1.0 if WAL/recovery strategy, 0.5 if basic durability, 0.0 if not addressed"),
                ("versioning", "Document history and version access for users", 0.20,
                 "1.0 if version history with access, 0.5 if basic, 0.0 if absent"),
            ]),
            pass_examples=["Ops log for real-time (Redis Streams), periodic snapshots to S3 (every 1000 ops or 5 min), snapshot + replay for crash recovery. History via snapshot chain."],
            fail_examples=["'Store documents in a database' — no specifics"],
        ),
        Criterion(
            id="sd_operational",
            category="production_readiness",
            description="Addresses operational concerns: monitoring, graceful degradation, SLOs, deployment",
            pass_condition="Defines: SLOs for latency and consistency, monitoring dashboards, "
                          "graceful degradation under load, zero-downtime deployment strategy, "
                          "and capacity planning for 100K concurrent users.",
            scoring=_weighted(8, [
                ("slos", "Specific SLOs for latency, consistency, and availability", 0.25,
                 "1.0 if numeric SLOs (e.g., p99 <200ms, 99.9% uptime), 0.5 if qualitative, 0.0 if absent"),
                ("monitoring", "Key metrics and dashboards for operational visibility", 0.25,
                 "1.0 if specific metrics (ops/sec, connection count, merge latency), 0.5 if generic, 0.0 if absent"),
                ("degradation", "Graceful degradation under load (read-only mode, reduced sync frequency)", 0.25,
                 "1.0 if specific degradation strategy, 0.5 if acknowledged, 0.0 if not addressed"),
                ("capacity_planning", "Back-of-envelope capacity estimates for 100K concurrent users", 0.25,
                 "1.0 if quantified (connections, bandwidth, storage), 0.5 if estimated, 0.0 if not addressed"),
            ]),
            pass_examples=["100K users × ~1 op/sec avg = 100K ops/sec. Each op ~200 bytes → 20 MB/s ingest. 10 document servers at 10K connections each. SLO: p99 sync <200ms, data loss window <5s."],
            fail_examples=["'The system should be highly available and performant' — no specifics"],
        ),
    ]

    return Rubric(
        task=task,
        domain="system_design",
        criteria=criteria,
        total_points=sum(c.scoring.max_points for c in criteria),
        pass_threshold=0.85,
    )


# ============================================================================
# Registry
# ============================================================================

ALL_SAMPLE_RUBRICS = [
    build_cold_outreach_email_rubric,       # 1
    build_csv_parser_rubric,                # 2
    build_exec_summary_rubric,              # 3
    build_sql_ltv_rubric,                   # 4
    build_counterargument_rubric,           # 5
    build_billing_schema_rubric,            # 6
    build_explanation_rubric,               # 7
    build_naming_rubric,                    # 8
    build_bash_backup_rubric,               # 9
    build_investment_memo_rubric,           # 10
    build_incident_postmortem_rubric,       # 11
    build_api_rate_limiter_rubric,          # 12
    build_legal_contract_redline_rubric,    # 13
    build_data_pipeline_dag_rubric,         # 14
    build_board_deck_narrative_rubric,      # 15
    build_security_threat_model_rubric,     # 16
    build_rust_concurrent_cache_rubric,     # 17
    build_comp_analysis_memo_rubric,        # 18
    build_ml_experiment_report_rubric,      # 19
    build_terraform_multi_env_rubric,       # 20
    build_negotiation_playbook_rubric,      # 21
    build_graphql_schema_federation_rubric, # 22
    build_regulatory_gap_analysis_rubric,   # 23
    build_debugging_walkthrough_rubric,     # 24
    build_system_design_doc_rubric,         # 25
]

SAMPLE_TASKS = {
    "cold_outreach_email": build_cold_outreach_email_rubric,
    "csv_parser": build_csv_parser_rubric,
    "exec_summary": build_exec_summary_rubric,
    "sql_ltv_query": build_sql_ltv_rubric,
    "agi_counterargument": build_counterargument_rubric,
    "billing_schema": build_billing_schema_rubric,
    "attention_explanation": build_explanation_rubric,
    "startup_naming": build_naming_rubric,
    "bash_backup": build_bash_backup_rubric,
    "investment_memo": build_investment_memo_rubric,
    "incident_postmortem": build_incident_postmortem_rubric,
    "api_rate_limiter": build_api_rate_limiter_rubric,
    "legal_contract_redline": build_legal_contract_redline_rubric,
    "data_pipeline_dag": build_data_pipeline_dag_rubric,
    "board_deck_narrative": build_board_deck_narrative_rubric,
    "security_threat_model": build_security_threat_model_rubric,
    "rust_concurrent_cache": build_rust_concurrent_cache_rubric,
    "comp_analysis_memo": build_comp_analysis_memo_rubric,
    "ml_experiment_report": build_ml_experiment_report_rubric,
    "terraform_multi_env": build_terraform_multi_env_rubric,
    "negotiation_playbook": build_negotiation_playbook_rubric,
    "graphql_schema_federation": build_graphql_schema_federation_rubric,
    "regulatory_gap_analysis": build_regulatory_gap_analysis_rubric,
    "debugging_walkthrough": build_debugging_walkthrough_rubric,
    "system_design_doc": build_system_design_doc_rubric,
}


def build_rubric_for_task(task_number: int) -> Rubric:
    """Build a sample rubric by task number (1-25)."""
    if not 1 <= task_number <= len(ALL_SAMPLE_RUBRICS):
        raise ValueError(f"Task number must be 1-{len(ALL_SAMPLE_RUBRICS)}, got {task_number}")
    return ALL_SAMPLE_RUBRICS[task_number - 1]()


# ============================================================================
# CLI — Print summary of all sample rubrics
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("SAMPLE RUBRICS — 10 Task-Specific Evaluation Systems")
    print("=" * 80)

    for i, builder in enumerate(ALL_SAMPLE_RUBRICS, 1):
        rubric = builder()
        print(f"\n{'─' * 70}")
        print(f"  Task {i}: {rubric.task[:65]}")
        print(f"  Domain: {rubric.domain} | Criteria: {len(rubric.criteria)} | "
              f"Max Points: {rubric.total_points} | Pass: {rubric.pass_threshold:.0%}")
        print(f"{'─' * 70}")

        for c in rubric.criteria:
            method = c.scoring.method.value
            pts = c.scoring.max_points
            n_sub = len(c.scoring.sub_attributes)
            n_pen = len(c.scoring.penalties)
            detail = f"{n_sub} subs" if n_sub else f"{n_pen} penalties" if n_pen else "binary"
            print(f"    {c.id:25s} | {c.category:20s} | {method:20s} | {pts:2d}pts | {detail}")

    print(f"\n{'=' * 80}")
    total_criteria = sum(len(builder().criteria) for builder in ALL_SAMPLE_RUBRICS)
    total_points = sum(builder().total_points for builder in ALL_SAMPLE_RUBRICS)
    print(f"TOTALS: {total_criteria} criteria across 10 rubrics, {total_points} max points")
    print(f"{'=' * 80}")
