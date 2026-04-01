# PathAgent Spec — Alternative Strategy Explorer

## Problem Statement

The harness's FeedbackAgent tells the generator **what's wrong** and **how to fix it** — but it always suggests incremental refinements within the same approach. When a criterion is stuck (failed to improve across 2+ iterations), the generator keeps making minor tweaks to a fundamentally flawed strategy instead of pivoting.

**Example (Run 6, attention_explanation):**
- Feedback: "completeness dropped — add more coverage of multi-head attention"
- Generator: adds a paragraph about multi-head attention (same explanatory framing)
- Score: still stuck at ~34% because the entire **approach** (metaphor-heavy, pop-culture analogies) is incompatible with completeness
- What was needed: pivot to a structured walkthrough approach, or a layered explanation (intuitive first, then deep dive)

The PathAgent breaks this loop by exploring **fundamentally different strategies** for stuck criteria and giving the generator a menu of alternatives.

## Architecture

### Position in the Loop

```
Current:
  Score → FeedbackAgent → format_for_generator() → GenerationAgent

New:
  Score → FeedbackAgent → format_for_generator() ─────────────────────┐
                                                                       ├→ GenerationAgent
  Score + History → PathAgent (for stuck criteria) → format_paths() ──┘
```

### Activation Criteria

PathAgent fires **only** when a criterion meets ALL of:
1. Scored below 50% in the current iteration
2. Failed to improve by >5pp across the last 2 iterations (stuck)
3. At least 2 iterations have elapsed (not triggered on iter 1-2)

This keeps it surgical — most criteria are handled fine by FeedbackAgent alone.

### Agent Design

```python
class PathAgent:
    """Explores alternative strategies for stuck criteria.

    Receives: criterion spec, measurement definition, last 2 attempts
    (content excerpts relevant to the criterion), scores, and feedback history.

    Returns: 2-3 ranked alternative approaches, each described in 2-3 sentences.
    The generator picks ONE and commits to it.

    Uses web search to ground alternatives in real-world best practices.
    """
```

**Isolation:** Own Anthropic client, own context window. Never sees scorer reasoning, rubric negotiation, or feedback agent internals. Follows the existing GAN-inspired separation.

**Model:** Same model as other agents (claude-sonnet-4-20250514).

**Web search:** Enabled. PathAgent should research domain-specific best practices (e.g., "best techniques for explaining technical concepts to teenagers" for the attention_explanation task).

### Input

PathAgent receives for each stuck criterion:

```python
{
    "criterion_id": str,
    "criterion_description": str,          # From rubric
    "measurement_spec": str,               # What scorer measures
    "current_score": float,                # Latest score
    "score_history": list[float],          # Score per iteration
    "current_approach_summary": str,       # 2-3 sentence summary of what generator is currently doing
    "failed_feedback": list[str],          # Last 2 feedback instructions that didn't help
    "task_description": str,               # The overall task
}
```

**`current_approach_summary`** is extracted by summarizing the content sections relevant to this criterion from the current iteration (lightweight LLM call or heuristic extraction).

### Output

```python
{
    "criterion_id": str,
    "current_approach": str,               # Brief description of what's being tried
    "alternatives": [
        {
            "rank": 1,
            "strategy": str,               # 2-3 sentence description of the alternative approach
            "why_it_might_work": str,       # 1 sentence rationale
            "example_signal": str,          # What a good implementation would look like (1 sentence)
        },
        # ... 2-3 alternatives total
    ],
    "recommendation": str,                 # Which alternative the PathAgent recommends and why
}
```

### Integration with Generator Prompt

Added as a new section in the EDIT_PROMPT, after STRUCTURED FEEDBACK:

```
ALTERNATIVE STRATEGIES (for stuck criteria — pick ONE and commit):

  STUCK: expl_completeness (34%, stuck for 3 iterations)
  Current approach: Using pop-culture analogies (Instagram, phone autocomplete) to explain attention.

  Alternative 1 (RECOMMENDED): Layered explanation — start with 3-sentence intuitive hook,
  then structured walkthrough of Q/K/V with a concrete example sentence. Cover multi-head
  in a dedicated subsection.
  Why: Separates engagement (hook) from completeness (structured deep-dive) instead of
  trying to do both simultaneously.

  Alternative 2: Worked example approach — pick one sentence ("The cat sat on the mat
  because it was tired") and trace the full attention computation step by step, introducing
  each concept (Q, K, V, multi-head) as needed.
  Why: Forces coverage of all components by requiring each in the worked example.

INSTRUCTION: Choose ONE alternative above. Do NOT blend them. Commit fully to the chosen
strategy for the sections addressing expl_completeness.
```

### Key Constraints

1. **Only for stuck criteria** — don't run on every criterion every iteration
2. **2-3 alternatives max** — not a brainstorm, a curated menu
3. **Generator picks ONE** — explicit instruction to commit, not blend
4. **Lock-in for 2 iterations** — once a path is chosen, don't generate new alternatives for 2 iterations (let the generator refine the chosen approach)
5. **Token budget** — PathAgent prompt should be <2K tokens in, <1K tokens out. Lightweight.
6. **No regression on passing criteria** — PathAgent alternatives must not suggest changes to criteria scoring >75%

## Implementation Plan

### Files to Modify

1. **`rubric_harness.py`** — Add PathAgent class, integrate into iteration loop
2. **`rubric_system/models.py`** — Add PathResult dataclass (optional, could use dict)

### Step 1: PathAgent Class (~100 lines)

Add after the FeedbackAgent class definition (~line 6430). Follows the same pattern:
- Own `__init__` with isolated Anthropic client
- `explore_alternatives()` method — main entry point
- `format_for_generator()` — formats output for injection into EDIT_PROMPT
- `_summarize_current_approach()` — extracts what the generator is doing for a criterion
- `_detect_stuck_criteria()` — static method to identify stuck criteria from history

### Step 2: Stuck Criteria Detection (~20 lines)

Add `_detect_stuck_criteria()` as a static method or module-level function:

```python
def detect_stuck_criteria(
    criterion_scores: list[CriterionScore],
    history: list[Iteration],
    min_iterations: int = 2,
    stuck_threshold: float = 0.05,   # <5pp improvement
    score_ceiling: float = 0.50,     # Only for criteria below 50%
) -> list[str]:
    """Return criterion_ids that are stuck."""
```

### Step 3: Integration into Main Loop (~15 lines)

In `RubricLoop.run()`, after feedback generation (line ~7847), add:

```python
# PathAgent: explore alternatives for stuck criteria (iteration 3+)
path_alternatives_text = ""
if i >= 3:  # Only after 2+ iterations
    stuck = detect_stuck_criteria(criterion_scores, history)
    if stuck:
        path_results = self.path_agent.explore_alternatives(
            stuck_criteria=stuck,
            criterion_scores=criterion_scores,
            rubric=rubric,
            history=history,
            current_content=content,
            task=rubric.task,
        )
        path_alternatives_text = self.path_agent.format_for_generator(path_results)
```

Then inject into `generate_content()` alongside structured_feedback.

### Step 4: Lock-in Tracking (~10 lines)

Track which criteria have active path choices to prevent re-exploring too soon:

```python
# In RubricLoop.__init__
self._path_locks: dict[str, int] = {}  # criterion_id → iteration when path was chosen

# In detection logic
if criterion_id in self._path_locks and (i - self._path_locks[criterion_id]) < 2:
    continue  # Still locked, let generator refine the chosen path
```

### Step 5: RubricLoop Constructor Update (~3 lines)

Add PathAgent to the component list:

```python
# Component 10: Path exploration agent (alternative strategy discovery)
self.path_agent = PathAgent(model=model, verbose=verbose)
```

## Verification Rubric

### Functional Correctness
- [ ] PathAgent only activates when criterion is stuck (below 50%, <5pp improvement over 2 iterations)
- [ ] PathAgent does NOT activate on iterations 1-2
- [ ] PathAgent returns exactly 2-3 alternatives per stuck criterion
- [ ] Alternatives are injected into generator prompt as a dedicated section
- [ ] Generator prompt explicitly instructs "pick ONE, don't blend"
- [ ] Lock-in prevents re-exploring same criterion for 2 iterations after path is chosen
- [ ] PathAgent has its own isolated Anthropic client (not shared)

### Integration
- [ ] Existing FeedbackAgent flow is unchanged — PathAgent is additive
- [ ] Structured feedback still appears in prompt (PathAgent section is separate)
- [ ] PathAgent section appears AFTER structured feedback in the prompt
- [ ] When no criteria are stuck, PathAgent section is empty (no prompt bloat)
- [ ] PathAgent results are persisted to disk alongside feedback files for auditability

### Regression Safety
- [ ] PathAgent alternatives never reference criteria scoring >75%
- [ ] Passing criteria remain in the "DO NOT CHANGE" section
- [ ] Lock-in mechanism prevents thrashing between different strategies
- [ ] Total token overhead per PathAgent call is <3K (prompt + response)

### Edge Cases
- [ ] Works when 0 criteria are stuck (no-op)
- [ ] Works when all criteria are stuck (generates alternatives for all)
- [ ] Works when PathAgent API call fails (graceful fallback — just use feedback only)
- [ ] Works with observation masking (uses current content, not masked history)
- [ ] Lock-in resets if score improves >10pp (path worked, allow re-exploration)

### Eval Validation
- [ ] Run eval on attention_explanation task — verify PathAgent activates on iter 3+
- [ ] Run eval on agi_counterargument — verify PathAgent does NOT activate (scores improve steadily)
- [ ] Run full 8-task eval — no regressions on previously passing tasks
- [ ] Compare mean delta with vs without PathAgent on 3+ runs
