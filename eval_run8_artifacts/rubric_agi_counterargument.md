# Rubric: agi_counterargument

**Task:** Write a counterargument to the claim 'AGI will arrive before 2030'
**Domain:** argumentation
**Total Points:** 36
**Pass Threshold:** 0.8

## Criteria

### 1. arg_steelman

- **Category:** intellectual_honesty
- **Description:** Steelmans the original claim before countering it
- **Pass Condition:** First paragraph presents the strongest version of the AGI-by-2030 case. Cites real scaling results, benchmarks, expert proponents. Shows the reader you understand why smart people believe this.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'steelman_quality', 'description': 'Presents strongest version of the claim', 'weight': 0.5, 'measurement': '1.0 if cites specific results/proponents, 0.5 if generic, 0.0 if strawman', 'thresholds': {}}, {'sub_id': 'specific_evidence', 'description': 'References real benchmarks, papers, or expert positions', 'weight': 0.3, 'measurement': '1.0 if 2+ specific references, 0.5 if 1, 0.0 if none', 'thresholds': {}}, {'sub_id': 'good_faith', 'description': 'Reader feels the argument was fairly represented', 'weight': 0.2, 'measurement': '1.0 if fair, 0.0 if dismissive/strawman', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'The case for AGI by 2030 is stronger than critics admit: GPT-4 to o3 showed...'

**Fail Examples:**

- 'Some people naively believe AGI is coming soon, but...'

---

### 2. arg_counter_quality

- **Category:** argumentation
- **Description:** Counterarguments are specific, non-obvious, and empirically grounded
- **Pass Condition:** 3+ distinct counter-threads. At least one challenges the definition of AGI. At least one is empirical (benchmarking issues, capability gaps). At least one is structural (alignment, deployment, regulation).

**Scoring:**

- method: weighted_components
- max_points: 12
- sub_attributes: [{'sub_id': 'argument_count', 'description': '3+ distinct counter-threads', 'weight': 0.2, 'measurement': '1.0 if 3+, 0.5 if 2, 0.0 if 1', 'thresholds': {}}, {'sub_id': 'definitional_challenge', 'description': "Challenges what 'AGI' means and why it matters", 'weight': 0.25, 'measurement': '1.0 if substantive definitional argument, 0.0 if skips it', 'thresholds': {}}, {'sub_id': 'empirical_grounding', 'description': 'Cites specific capability gaps, benchmark limitations', 'weight': 0.3, 'measurement': '1.0 if specific gaps with evidence, 0.5 if general, 0.0 if hand-wavy', 'thresholds': {}}, {'sub_id': 'structural_barriers', 'description': 'Addresses alignment, regulation, deployment realities', 'weight': 0.25, 'measurement': '1.0 if specific structural argument, 0.5 if mentioned, 0.0 if absent', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Definitional ambiguity + benchmark saturation without real-world transfer + regulatory friction

**Fail Examples:**

- 'AI is overhyped' repeated three different ways

---

### 3. arg_nuance

- **Category:** sophistication
- **Description:** Avoids absolutism — acknowledges uncertainty and conditions
- **Pass Condition:** Uses probabilistic language. Identifies conditions under which the claim could be true. Distinguishes 'narrow AGI' from 'transformative AI'. Doesn't claim to know the answer.

**Scoring:**

- method: penalty_based
- max_points: 8
- sub_attributes: []
- penalties: {'absolutist_claim': -2.5, 'dismisses_without_evidence': -2.0, 'ignores_counterexamples': -1.5, 'no_uncertainty_acknowledgment': -2.0, 'appeal_to_authority_only': -1.0}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'AGI by 2030 is possible but improbable — here's why the base rate for such predictions is poor'

**Fail Examples:**

- 'AGI will definitely not happen by 2030'

---

### 4. arg_readability

- **Category:** communication
- **Description:** Well-structured, scannable, persuasive prose
- **Pass Condition:** Clear thesis in first paragraph. Each counter-thread in its own section. Conclusion synthesizes. Under 800 words.

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'structure', 'description': 'Thesis → steelman → counters → synthesis', 'weight': 0.4, 'measurement': '1.0 if clear structure, 0.5 if partially organized, 0.0 if stream of consciousness', 'thresholds': {}}, {'sub_id': 'concision', 'description': 'Under 800 words, no padding', 'weight': 0.3, 'measurement': '1.0 if ≤800, 0.7 if ≤1000, 0.0 if >1200', 'thresholds': {}}, {'sub_id': 'persuasive_flow', 'description': 'Builds momentum, ends strong', 'weight': 0.3, 'measurement': '1.0 if compelling arc, 0.5 if flat, 0.0 if scattered', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 700 words, clear sections, ends with a memorable reframe

**Fail Examples:**

- 1500-word stream of consciousness with no structure

---
