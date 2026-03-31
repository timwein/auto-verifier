#!/usr/bin/env python3
"""
Generate expert-quality rubrics for the 15 new eval tasks via the full
RubricAgent pipeline (research → expert persona → multi-pass → adversarial audit).

Saves each rubric as a JSON file in generated_rubrics/ and prints a summary.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rubric_harness import RubricAgent
from rubric_system.models import Rubric, ScoringMethod

# The 15 new task descriptions (must match sample_rubrics.py task strings)
NEW_TASKS = {
    "incident_postmortem": (
        "Write a blameless incident postmortem for a 4-hour production outage caused by "
        "a cascading failure across 3 microservices, including timeline, root cause, "
        "contributing factors, and action items"
    ),
    "api_rate_limiter": (
        "Design and implement a Python token-bucket rate limiter with sliding window support, "
        "Redis backend, distributed coordination, and graceful degradation when Redis is unavailable"
    ),
    "legal_contract_redline": (
        "Redline a cloud services SaaS agreement from the customer's perspective, identifying "
        "10 risky clauses and proposing specific alternative language with justification for each"
    ),
    "data_pipeline_dag": (
        "Design an Airflow DAG (Python) for an ETL pipeline that ingests from 3 sources "
        "(REST API, S3 parquet, PostgreSQL), handles schema drift, implements idempotent "
        "upserts, and includes alerting and retry logic"
    ),
    "board_deck_narrative": (
        "Write the narrative script (speaker notes) for a 12-slide Series B board deck "
        "covering financials, product roadmap, competitive landscape, hiring plan, and key risks, "
        "for a $30M ARR vertical SaaS company"
    ),
    "security_threat_model": (
        "Produce a STRIDE threat model for a mobile banking app with biometric auth, "
        "P2P payments, and third-party integrations, including threat matrix, risk ratings, "
        "and prioritized mitigations"
    ),
    "rust_concurrent_cache": (
        "Implement a thread-safe LRU cache in Rust with TTL expiry, bounded memory, and "
        "lock-free reads using Arc, RwLock, and background eviction, including comprehensive "
        "error handling"
    ),
    "comp_analysis_memo": (
        "Write a competitive analysis memo comparing 4 AI code assistant tools (Cursor, GitHub Copilot, "
        "Cody, Windsurf) across 8 dimensions with a recommendation for a 200-person engineering org"
    ),
    "ml_experiment_report": (
        "Write a reproducible ML experiment report for fine-tuning a language model on "
        "domain-specific data, covering dataset construction, training methodology, evaluation "
        "metrics, ablation results, and failure analysis"
    ),
    "terraform_multi_env": (
        "Write Terraform HCL for a production-grade AWS deployment with VPC, ECS Fargate, "
        "RDS, and ALB across dev/staging/prod environments using workspaces and modules, "
        "with least-privilege IAM"
    ),
    "negotiation_playbook": (
        "Create a procurement negotiation playbook for a $500K enterprise SaaS deal, including "
        "BATNA analysis, concession strategy, anchoring tactics, and scripted responses to "
        "5 common vendor objections"
    ),
    "graphql_schema_federation": (
        "Design a federated GraphQL schema for an e-commerce platform spanning 4 subgraphs "
        "(users, products, orders, payments) with proper entity resolution, auth directives, "
        "and N+1 prevention"
    ),
    "regulatory_gap_analysis": (
        "Perform a SOC 2 Type II readiness gap analysis for a 50-person B2B SaaS startup, "
        "identifying control gaps across all 5 trust service criteria with remediation "
        "priorities and estimated timelines"
    ),
    "debugging_walkthrough": (
        "Write a step-by-step debugging walkthrough for a race condition in a Node.js Express "
        "app where concurrent requests to a shared PostgreSQL connection pool cause intermittent "
        "500 errors under load"
    ),
    "system_design_doc": (
        "Write a system design document for a real-time collaborative document editor "
        "supporting 100K concurrent users, covering CRDT vs OT tradeoffs, conflict resolution, "
        "persistence layer, and operational concerns"
    ),
}

OUTPUT_DIR = Path("generated_rubrics")


def rubric_to_dict(rubric: Rubric) -> dict:
    """Serialize a Rubric to a JSON-compatible dict."""
    criteria_list = []
    for c in rubric.criteria:
        crit = {
            "id": c.id,
            "category": c.category,
            "description": c.description,
            "pass_condition": c.pass_condition,
            "scoring": {
                "method": c.scoring.method.value if hasattr(c.scoring.method, 'value') else str(c.scoring.method),
                "max_points": c.scoring.max_points,
            },
            "pass_examples": c.pass_examples if hasattr(c, 'pass_examples') else [],
            "fail_examples": c.fail_examples if hasattr(c, 'fail_examples') else [],
        }
        if hasattr(c, 'research_basis') and c.research_basis:
            crit["research_basis"] = c.research_basis
        if c.scoring.sub_attributes:
            crit["scoring"]["sub_attributes"] = [
                {
                    "sub_id": s.sub_id,
                    "description": s.description,
                    "weight": s.weight,
                    "measurement": s.measurement,
                }
                for s in c.scoring.sub_attributes
            ]
        if c.scoring.penalties:
            crit["scoring"]["penalties"] = c.scoring.penalties
        if hasattr(c.scoring, 'tiers') and c.scoring.tiers:
            crit["scoring"]["tiers"] = c.scoring.tiers
        criteria_list.append(crit)

    result = {
        "task": rubric.task,
        "domain": rubric.domain,
        "criteria": criteria_list,
        "total_points": rubric.total_points,
        "pass_threshold": rubric.pass_threshold,
    }
    if hasattr(rubric, 'dimensions') and rubric.dimensions:
        result["dimensions"] = [
            {"id": d.id, "name": d.name, "weight": d.weight, "criteria_ids": d.criteria_ids}
            for d in rubric.dimensions
        ]
    return result


def generate_single_rubric(task_key: str, task_desc: str) -> dict:
    """Generate a rubric for one task through the full pipeline."""
    print(f"\n{'='*70}")
    print(f"Generating rubric: {task_key}")
    print(f"Task: {task_desc[:80]}...")
    print(f"{'='*70}")

    agent = RubricAgent(
        model="claude-sonnet-4-20250514",
        verbose=True,
        enable_research=True,
        enable_expert_persona=True,
        enable_expert_panel=False,
        enable_exemplar=True,
        enable_rubric_store=True,
        enable_multipass=True,
        enable_adversarial_audit=True,
    )

    t0 = time.monotonic()
    rubric = agent.generate(task_desc)
    elapsed = time.monotonic() - t0

    print(f"\n[{task_key}] Generated: {len(rubric.criteria)} criteria, "
          f"{rubric.total_points} points, {elapsed:.1f}s")

    return rubric_to_dict(rubric)


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Check which tasks already have generated rubrics (resume support)
    remaining = {}
    for key, desc in NEW_TASKS.items():
        outfile = OUTPUT_DIR / f"{key}.json"
        if outfile.exists():
            print(f"[skip] {key} — already generated")
        else:
            remaining[key] = desc

    if not remaining:
        print("All 15 rubrics already generated!")
        return

    print(f"\n{len(remaining)} rubrics to generate...")

    for key, desc in remaining.items():
        try:
            rubric_dict = generate_single_rubric(key, desc)
            outfile = OUTPUT_DIR / f"{key}.json"
            outfile.write_text(json.dumps(rubric_dict, indent=2))
            print(f"[saved] {outfile}")
        except Exception as e:
            print(f"[ERROR] {key}: {e}")
            import traceback
            traceback.print_exc()

    # Print summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for key in NEW_TASKS:
        outfile = OUTPUT_DIR / f"{key}.json"
        if outfile.exists():
            data = json.loads(outfile.read_text())
            print(f"  {key:30s} {len(data['criteria']):2d} criteria  {data['total_points']:3d} points")
        else:
            print(f"  {key:30s} MISSING")


if __name__ == "__main__":
    main()
