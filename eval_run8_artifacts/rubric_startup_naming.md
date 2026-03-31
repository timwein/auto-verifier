# Rubric: startup_naming

**Task:** Generate 5 names for a startup that does AI-powered contract review for mid-market law firms
**Domain:** creative_naming
**Total Points:** 36
**Pass Threshold:** 0.75

## Criteria

### 1. name_count

- **Category:** structure
- **Description:** Exactly 5 names provided, each with rationale
- **Pass Condition:** Exactly 5 names. Each has 1-2 sentence rationale explaining the thinking behind it.

**Scoring:**

- method: binary
- max_points: 4
- sub_attributes: []
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 5 names, each with explanation of etymology and positioning

**Fail Examples:**

- 3 names with no explanation, or 10 names dumped

---

### 2. name_memorability

- **Category:** quality
- **Description:** Names are memorable, pronounceable, and pass the 'phone test'
- **Pass Condition:** Each name: ≤3 syllables preferred, no awkward letter combos, survives being spoken aloud, doesn't require spelling out.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'pronounceability', 'description': 'Names can be said aloud without confusion', 'weight': 0.4, 'measurement': '% of names that pass the phone test (say it, spell it)', 'thresholds': {}}, {'sub_id': 'brevity', 'description': 'Short, punchy — ideally ≤3 syllables', 'weight': 0.3, 'measurement': '% of names at ≤3 syllables', 'thresholds': {}}, {'sub_id': 'distinctiveness', 'description': "Doesn't blend in with existing brands", 'weight': 0.3, 'measurement': '% of names that are distinct from obvious competitors', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Clause' — 1 syllable, legal meaning, memorable

**Fail Examples:**

- 'IntelliLegalContractAI' — unmemorable, generic compound

---

### 3. name_domain_resonance

- **Category:** relevance
- **Description:** Names signal legal/contract/AI domain without being generic
- **Pass Condition:** Names evoke precision, trust, intelligence, or legal concepts. Not generic 'AI' prefix/suffix spam. Would feel at home on a law firm partner's desk.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'domain_signal', 'description': 'Evokes legal/contract/precision without being literal', 'weight': 0.4, 'measurement': '% of names with subtle domain resonance', 'thresholds': {}}, {'sub_id': 'avoids_generic_ai', 'description': "No 'AI' prefix/suffix, no '-ify', no 'Smart[X]'", 'weight': 0.3, 'measurement': '% of names avoiding generic tech naming patterns', 'thresholds': {}}, {'sub_id': 'trust_register', 'description': 'Would a law firm partner take a meeting with this company?', 'weight': 0.3, 'measurement': '% of names that feel professional enough for legal market', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Redline' — contract review term, implies precision and editing

**Fail Examples:**

- 'ContractAI', 'SmartReview', 'LegalBot'

---

### 4. name_availability

- **Category:** practicality
- **Description:** Names are likely available — .com plausible, not taken by major brands
- **Pass Condition:** At least 3/5 names have plausible .com availability (not common English words). None are existing well-known brands. Notes on availability included.

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'domain_plausibility', 'description': 'Names likely have .com available or reasonable variant', 'weight': 0.5, 'measurement': '% of names where .com is plausible (not a common English word)', 'thresholds': {}}, {'sub_id': 'no_trademark_conflicts', 'description': 'Not an existing well-known brand name', 'weight': 0.5, 'measurement': '% of names with no obvious trademark conflict', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Clausebound' — coined word, .com likely available

**Fail Examples:**

- 'Scout' — common word, definitely taken

---

### 5. name_variety

- **Category:** range
- **Description:** Names span different naming strategies — not all the same pattern
- **Pass Condition:** Mix of approaches: metaphorical, coined, real-word-repurposed, compound, classical/Latin root. At least 3 different strategies.

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'strategy_diversity', 'description': 'At least 3 different naming strategies used', 'weight': 0.5, 'measurement': '1.0 if 4+ strategies, 0.75 if 3, 0.5 if 2, 0.0 if all same', 'thresholds': {}}, {'sub_id': 'range_of_tone', 'description': 'Mix of serious/approachable/bold', 'weight': 0.5, 'measurement': '1.0 if clear tonal range, 0.5 if some variation, 0.0 if monotone', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Metaphorical (Redline) + coined (Clausefy) + classical (Lex Machina) + compound (Inkwell)

**Fail Examples:**

- 5 variations of '[Legal word] + AI'

---
