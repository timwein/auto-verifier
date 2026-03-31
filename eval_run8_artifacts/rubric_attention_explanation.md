# Rubric: attention_explanation

**Task:** Explain transformer attention mechanisms to a smart 16-year-old
**Domain:** explanation
**Total Points:** 36
**Pass Threshold:** 0.8

## Criteria

### 1. expl_accuracy

- **Category:** correctness
- **Description:** Technical content is correct — no simplification-induced errors
- **Pass Condition:** Query/Key/Value framework explained correctly. Dot product similarity is accurate. Softmax described correctly. Multi-head attention's purpose is right.

**Scoring:**

- method: weighted_components
- max_points: 12
- sub_attributes: [{'sub_id': 'qkv_correctness', 'description': 'Q/K/V roles explained accurately', 'weight': 0.35, 'measurement': '1.0 if correct mechanism, 0.5 if metaphor-only, 0.0 if wrong', 'thresholds': {}}, {'sub_id': 'attention_math', 'description': 'Dot product + softmax pipeline correct', 'weight': 0.35, 'measurement': '1.0 if mechanism right, 0.5 if hand-wavy but directionally correct, 0.0 if wrong', 'thresholds': {}}, {'sub_id': 'multihead_purpose', 'description': 'Why multiple heads matter', 'weight': 0.3, 'measurement': '1.0 if explains different relationship types, 0.5 if mentions it, 0.0 if absent', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Each word asks a question (query), advertises what it knows (key), and shares details (value)'

**Fail Examples:**

- 'Attention is when the model focuses on important words' — no mechanism

---

### 2. expl_accessibility

- **Category:** audience_fit
- **Description:** A smart 16-year-old actually understands it after reading
- **Pass Condition:** No unexplained jargon. Uses analogies from their world. Builds from familiar concepts (search, recommendation) to new ones. Math level: algebra ok, linear algebra explained if used.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'jargon_handling', 'description': 'All technical terms explained or avoided', 'weight': 0.3, 'measurement': '1.0 if all explained, 0.5 if most, 0.0 if jargon-heavy', 'thresholds': {}}, {'sub_id': 'analogy_quality', 'description': 'Uses relatable analogies (social media, school, etc.)', 'weight': 0.35, 'measurement': '1.0 if memorable analogy that maps correctly, 0.5 if generic, 0.0 if none', 'thresholds': {}}, {'sub_id': 'progressive_complexity', 'description': 'Builds from simple to complex', 'weight': 0.35, 'measurement': '1.0 if clear scaffold, 0.5 if some structure, 0.0 if jumps to hard parts', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Starts with 'imagine searching for a video on YouTube' → builds to Q/K/V

**Fail Examples:**

- 'Attention computes softmax(QK^T/√d_k)V' with no unpacking

---

### 3. expl_engagement

- **Category:** communication
- **Description:** Explanation is engaging — a 16-year-old would actually read to the end
- **Pass Condition:** Conversational tone. Not condescending. Includes a 'whoa' moment. Under 600 words. Has a hook in the first sentence.

**Scoring:**

- method: weighted_components
- max_points: 8
- sub_attributes: [{'sub_id': 'hook', 'description': 'First sentence creates curiosity', 'weight': 0.3, 'measurement': '1.0 if compelling hook, 0.5 if adequate, 0.0 if textbook opening', 'thresholds': {}}, {'sub_id': 'tone', 'description': 'Conversational, not textbook or condescending', 'weight': 0.35, 'measurement': '1.0 if natural, 0.5 if slightly formal, 0.0 if textbook/patronizing', 'thresholds': {}}, {'sub_id': 'concision', 'description': 'Under 600 words, no padding', 'weight': 0.35, 'measurement': '1.0 if ≤600, 0.7 if ≤800, 0.0 if >1000', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'You know how autocomplete seems to read your mind? Here's the trick...'

**Fail Examples:**

- 'Attention mechanisms are a fundamental component of transformer architectures...'

---

### 4. expl_completeness

- **Category:** coverage
- **Description:** Covers the essential pieces without going too deep
- **Pass Condition:** Covers: why attention exists (context problem), how it works (Q/K/V), why it matters (parallel processing, long-range dependencies). Doesn't require covering positional encoding, layer norm, etc.

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'motivation', 'description': 'Explains why attention was invented (the problem it solves)', 'weight': 0.35, 'measurement': '1.0 if clear problem statement, 0.5 if implied, 0.0 if jumps to mechanism', 'thresholds': {}}, {'sub_id': 'mechanism', 'description': 'How attention works at an intuitive level', 'weight': 0.35, 'measurement': '1.0 if clear mechanism, 0.0 if vague', 'thresholds': {}}, {'sub_id': 'significance', 'description': 'Why it matters / what it enabled', 'weight': 0.3, 'measurement': '1.0 if connects to real impact, 0.5 if mentioned, 0.0 if absent', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Problem (RNNs forget) → Mechanism (Q/K/V attention) → Impact (ChatGPT, translation)

**Fail Examples:**

- Deep dive into multi-head attention math with no motivation

---
