from __future__ import annotations
"""
Stage 5 Quality Gate — post-generation filter for rubric discriminative power.

Runs after rubric generation and trade-off detection but before the gen-verify loop.
Three checks in a single LLM call:
  1. Discriminative power  — tighten or remove criteria a baseline trivially passes
  2. Redundancy removal     — merge semantically duplicate criteria (RRD-style)
  3. Measurability          — rewrite vague pass conditions to be binary-checkable
"""

import json
import re
from dataclasses import replace as dc_replace
from typing import List, Optional, Tuple

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


class RubricQualityGate:
    """Post-generation rubric quality filter.

    Isolated context window — only sees the rubric and a quick imagined baseline
    output.  Runs after trade-off detection, before the gen-verify loop starts.

    Three checks (single LLM call):
      1. Discriminative power  — any criterion the baseline clears at >80% is
         either tightened (pass condition made stricter) or removed.
      2. Redundancy/correlation — semantically duplicate criteria are merged so
         that two criteria cannot always score the same way on any reasonable output.
      3. Measurability          — vague pass conditions are rewritten to be
         concrete and binary-checkable.
    """

    SYSTEM_PROMPT = (
        "You are a rubric quality analyst. Your job is to improve the discriminative "
        "power, uniqueness, and measurability of scoring rubrics.\n\n"
        "You will receive:\n"
        "  - A task description\n"
        "  - A list of rubric criteria (with pass conditions)\n\n"
        "Your job is to do three things in one pass:\n\n"
        "STEP 1 — Generate a quick, plausible BASELINE OUTPUT for the task.\n"
        "  The baseline is what a capable but unremarkable AI produces with no special "
        "guidance: adequate, competent, and generic. Not terrible, not excellent.\n\n"
        "STEP 2 — Score the baseline against each criterion on a 0-100% scale.\n"
        "  Ask yourself: 'Would a scorer award this criterion full points for the "
        "baseline?' If yes (>80%), the criterion is non-discriminative — a baseline "
        "passes it trivially.\n\n"
        "STEP 3 — Analyze each criterion for three quality issues:\n"
        "  A. Non-discriminative (baseline score >80%):\n"
        "     -> Action: 'tighten' (make pass condition stricter and more demanding)\n"
        "        OR 'remove' (if the criterion is generic/aspirational and cannot be "
        "tightened meaningfully)\n"
        "  B. Redundant (semantically overlaps another criterion — would always score "
        "the same):\n"
        "     -> Action: 'merge' (merge into another criterion; specify which one)\n"
        "        OR 'remove' (if it is fully subsumed)\n"
        "  C. Vague pass condition (e.g., 'is well-written', 'is clear', 'is "
        "comprehensive'):\n"
        "     -> Action: 'rewrite' (provide a concrete, binary-checkable pass "
        "condition)\n\n"
        "Important constraints:\n"
        "- Be conservative: only flag genuine problems. A criterion covering unique "
        "quality signal should NOT be touched even if similar in topic to another.\n"
        "- Tightening means raising the bar, not rephrasing the same bar.\n"
        "- Merging must preserve both quality signals in a single criterion.\n"
        "- Rewrites must be concrete and binary: a scorer can determine pass/fail "
        "without subjective judgment.\n"
        "- You must be GENERAL PURPOSE: do not assume any particular domain.\n\n"
        "Return only JSON — no prose outside the JSON block."
    )

    def __init__(self, model: str = "claude-sonnet-4-20250514", verbose: bool = True):
        if Anthropic is None:
            raise ImportError("anthropic package required: pip install anthropic")
        self.client = Anthropic(timeout=__import__('httpx').Timeout(600.0, connect=30.0))
        self.model = model
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[QualityGate] {msg}")

    def run(self, rubric: "Rubric", task: str) -> Tuple["Rubric", List[str]]:  # type: ignore[name-defined]
        """Run all three quality checks and return a refined rubric.

        Returns:
            (refined_rubric, gate_messages) — gate_messages describes every
            change made; empty list if no changes were needed.
        """
        if not rubric.criteria:
            return rubric, []

        criteria_json = [
            {
                "id": c.id,
                "description": c.description,
                "pass_condition": c.pass_condition,
                "max_points": c.scoring.max_points,
            }
            for c in rubric.criteria
        ]

        prompt = (
            f"TASK:\n{task}\n\n"
            f"RUBRIC CRITERIA:\n{json.dumps(criteria_json, indent=2)}\n\n"
            "Complete all three steps described in the system prompt and return JSON "
            "in this exact format:\n"
            "{\n"
            '  "baseline_summary": "One sentence describing the quick baseline output '
            'you imagined",\n'
            '  "criteria_actions": [\n'
            "    {\n"
            '      "criterion_id": "exact_id_from_rubric",\n'
            '      "baseline_score_pct": 75,\n'
            '      "issues": ["non_discriminative", "vague"],\n'
            '      "action": "tighten|remove|merge|rewrite|keep",\n'
            '      "merge_into": "other_criterion_id",\n'
            '      "new_description": "...",\n'
            '      "new_pass_condition": "...",\n'
            '      "reason": "One sentence explaining the change"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Include ALL criteria in criteria_actions, even those with action 'keep'\n"
            "- 'merge' action requires a 'merge_into' field pointing to the absorbing "
            "criterion\n"
            "- 'tighten' and 'rewrite' require updated 'new_pass_condition' (and "
            "optionally 'new_description')\n"
            "- 'remove' and 'keep' need only 'reason'\n"
            "- Only include 'new_description' / 'new_pass_condition' when the action "
            "requires a change\n"
            "- A criterion can have multiple issues but only one action\n\n"
            "If no criteria need changes, return all actions as 'keep'."
        )

        self._log(f"Running quality gate on {len(rubric.criteria)} criteria...")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=6000,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text

        result: dict = {}
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
        raw_json = m.group(1) if m else raw
        try:
            result = json.loads(raw_json.strip())
        except Exception:
            m2 = re.search(r'\{[\s\S]*\}', raw)
            if m2:
                try:
                    result = json.loads(m2.group())
                except Exception:
                    self._log("Failed to parse quality gate response — returning rubric unchanged.")
                    return rubric, []

        baseline_summary = result.get("baseline_summary", "")
        if baseline_summary:
            self._log(f"Baseline: {baseline_summary[:100]}")

        actions = result.get("criteria_actions", [])
        if not actions:
            self._log("No quality issues found.")
            return rubric, []

        # Build mutable lookup; track criteria removed or absorbed by merges
        criteria_map = {c.id: c for c in rubric.criteria}
        removed_ids: set = set()
        gate_messages: List[str] = []

        # Index actions by criterion_id
        action_map: dict = {}
        for a in actions:
            cid = a.get("criterion_id", "")
            if cid:
                action_map[cid] = a

        # First pass: handle merges.  The absorbing criterion is updated to
        # incorporate the merged-away criterion's quality signal.
        for cid, action_data in action_map.items():
            if action_data.get("action") != "merge":
                continue
            if cid not in criteria_map or cid in removed_ids:
                continue
            absorb_into = action_data.get("merge_into", "")
            if not absorb_into or absorb_into not in criteria_map:
                self._log(
                    f"  Skipping merge for {cid!r}: "
                    f"merge_into target {absorb_into!r} not found"
                )
                continue

            source = criteria_map[cid]
            target = criteria_map[absorb_into]
            reason = action_data.get("reason", "")

            # Prefer the absorbing criterion's own tighten/rewrite result if present
            absorb_action = action_map.get(absorb_into, {})
            new_desc = (
                absorb_action.get("new_description")
                or f"{target.description}; also: {source.description}"
            )
            new_pass = (
                absorb_action.get("new_pass_condition")
                or target.pass_condition
            )
            # Roll the merged criterion's points into the absorbing one
            new_scoring = dc_replace(
                target.scoring,
                max_points=target.scoring.max_points + source.scoring.max_points,
            )
            criteria_map[absorb_into] = dc_replace(
                target,
                description=new_desc,
                pass_condition=new_pass,
                scoring=new_scoring,
            )
            removed_ids.add(cid)
            msg = f"[merge] {cid} -> {absorb_into}: {reason[:80]}"
            gate_messages.append(msg)
            self._log(f"  {msg}")

        # Second pass: tighten / rewrite / remove remaining criteria
        for cid, action_data in action_map.items():
            act = action_data.get("action", "keep")
            if act in ("keep", "merge"):
                continue
            if cid not in criteria_map or cid in removed_ids:
                continue

            criterion = criteria_map[cid]
            reason = action_data.get("reason", "")

            if act == "remove":
                removed_ids.add(cid)
                msg = f"[remove] {cid}: {reason[:80]}"
                gate_messages.append(msg)
                self._log(f"  {msg}")

            elif act in ("tighten", "rewrite"):
                new_desc = action_data.get("new_description") or criterion.description
                new_pass = action_data.get("new_pass_condition") or criterion.pass_condition
                criteria_map[cid] = dc_replace(
                    criterion,
                    description=new_desc,
                    pass_condition=new_pass,
                )
                label = "tighten" if act == "tighten" else "rewrite"
                msg = f"[{label}] {cid}: {reason[:80]}"
                gate_messages.append(msg)
                self._log(f"  {msg}")

            else:
                self._log(f"  Unknown action {act!r} for {cid!r}, skipping")

        # Deterministic check: scale penalty sums that exceed 1.3x max_points
        for cid, criterion in criteria_map.items():
            if cid in removed_ids:
                continue
            if (hasattr(criterion.scoring, 'method')
                    and criterion.scoring.method.value == "penalty_based"
                    and criterion.scoring.penalties):
                total_penalty = sum(abs(p) for p in criterion.scoring.penalties.values())
                max_pts = criterion.scoring.max_points
                if total_penalty > max_pts * 1.3:
                    scale_factor = (max_pts * 1.3) / total_penalty
                    new_penalties = {
                        k: round(v * scale_factor, 1)
                        for k, v in criterion.scoring.penalties.items()
                    }
                    criteria_map[cid] = dc_replace(
                        criterion,
                        scoring=dc_replace(criterion.scoring, penalties=new_penalties),
                    )
                    msg = (f"[scale-penalties] {cid}: penalties "
                           f"{total_penalty:.1f} -> "
                           f"{sum(abs(v) for v in new_penalties.values()):.1f} "
                           f"(was {total_penalty / max_pts:.1f}x max_points)")
                    gate_messages.append(msg)
                    self._log(f"  {msg}")

        # Reconstruct criteria in original order, dropping removed/merged criteria
        new_criteria = [
            criteria_map[c.id]
            for c in rubric.criteria
            if c.id not in removed_ids
        ]
        new_total = sum(c.scoring.max_points for c in new_criteria)
        refined_rubric = dc_replace(rubric, criteria=new_criteria, total_points=new_total)

        # Validation warnings: criterion granularity
        oversized = [c for c in new_criteria if c.scoring.max_points > 8]
        if oversized:
            self._log(
                f"  WARNING: {len(oversized)} criteria exceed 8 max_points: "
                + ", ".join(f"{c.id}({c.scoring.max_points}pts)" for c in oversized[:5])
            )
        if len(new_criteria) < 8:
            self._log(
                f"  WARNING: Only {len(new_criteria)} criteria "
                f"(recommended minimum: 8 for scoring granularity)"
            )

        if gate_messages:
            self._log(
                f"Quality gate complete: {len(gate_messages)} change(s) — "
                f"{len(new_criteria)} criteria remain "
                f"(was {len(rubric.criteria)}), "
                f"{new_total}pts total (was {rubric.total_points}pts)."
            )
        else:
            self._log("Quality gate: no changes needed.")

        return refined_rubric, gate_messages
