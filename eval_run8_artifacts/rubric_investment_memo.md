# Rubric: investment_memo

**Task:** Draft a 1-page investment memo on a hypothetical Series A company in the defense drone space
**Domain:** investment_memo
**Total Points:** 44
**Pass Threshold:** 0.85

## Criteria

### 1. memo_structure

- **Category:** format
- **Description:** Follows standard 1-page memo format with all required sections
- **Pass Condition:** Sections: Company Overview, Market Opportunity, Product/Technology, Team, Traction, Deal Terms, Key Risks, Recommendation. Fits on one page (~500-700 words).

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'section_coverage', 'description': 'All required sections present', 'weight': 0.35, 'measurement': '% of required sections (overview, market, product, team, traction, terms, risks, rec)', 'thresholds': {}}, {'sub_id': 'page_constraint', 'description': 'Fits on one page (500-700 words)', 'weight': 0.3, 'measurement': '1.0 if 500-700 words, 0.7 if 700-850, 0.3 if 400-500, 0.0 if >900', 'thresholds': {}}, {'sub_id': 'scannable_format', 'description': 'Headers, bullets within sections, dense but readable', 'weight': 0.35, 'measurement': '1.0 if scannable with clear visual hierarchy, 0.0 if wall of text', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 8 sections, 650 words, each section 2-4 bullet points

**Fail Examples:**

- 3-page narrative essay, or 200-word skim

---

### 2. memo_market

- **Category:** analysis
- **Description:** Market opportunity is sized and specific to defense drones, not generic TAM
- **Pass Condition:** SAM/SOM, not just TAM. Specific to defense drone segment. Cites or constructs credible numbers. Identifies tailwinds (DoD budget trends, Ukraine lessons, NDAA provisions).

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'market_specificity', 'description': "Defense drone SAM, not generic 'drone market'", 'weight': 0.35, 'measurement': '1.0 if defense-specific SAM/SOM, 0.5 if TAM only, 0.0 if generic', 'thresholds': {}}, {'sub_id': 'credible_sizing', 'description': 'Numbers are plausible with cited or constructed basis', 'weight': 0.3, 'measurement': '1.0 if sourced/constructed, 0.5 if asserted, 0.0 if absent', 'thresholds': {}}, {'sub_id': 'tailwind_identification', 'description': 'Specific policy/geopolitical tailwinds cited', 'weight': 0.35, 'measurement': '% of relevant tailwinds identified (DoD budget, NDAA, Ukraine, Replicator)', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Defense sUAS SAM: $8B by 2028 (up from $3B), driven by DoD Replicator initiative and FY26 NDAA line items'

**Fail Examples:**

- 'The global drone market is expected to reach $50B by 2030'

---

### 3. memo_thesis

- **Category:** conviction
- **Description:** Investment thesis is crisp — clear 'why this company, why now'
- **Pass Condition:** 2-3 sentence thesis that answers: What's the insight? Why is this team positioned? What's the timing catalyst? Must be specific enough that it couldn't apply to any defense startup.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'insight_clarity', 'description': 'Core insight is specific and non-obvious', 'weight': 0.4, 'measurement': '1.0 if specific insight, 0.5 if generic but directionally right, 0.0 if boilerplate', 'thresholds': {}}, {'sub_id': 'team_match', 'description': 'Why this team specifically is positioned to win', 'weight': 0.3, 'measurement': '1.0 if specific team-market fit, 0.5 if generic team praise, 0.0 if absent', 'thresholds': {}}, {'sub_id': 'timing_catalyst', 'description': "Clear 'why now' with specific catalyst", 'weight': 0.3, 'measurement': '1.0 if specific timing argument, 0.5 if vague, 0.0 if absent', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'DoD is shifting from $50M primes-built systems to $500K attritable drones — [Company] has the only NDAA-compliant autonomy stack that integrates with existing C2 systems, built by ex-Anduril engineers who shipped the first production Altius system.'

**Fail Examples:**

- 'Defense is a big market and drones are the future.'

---

### 4. memo_risks

- **Category:** diligence
- **Description:** Key risks are honest, specific, and include mitigants
- **Pass Condition:** 3-5 real risks (not strawmen). At least one each: market risk, execution risk, regulatory/ITAR risk. Each has a mitigant or monitoring plan.

**Scoring:**

- method: weighted_components
- max_points: 8
- sub_attributes: [{'sub_id': 'risk_quality', 'description': 'Risks are real and specific, not generic', 'weight': 0.4, 'measurement': '% of risks that are specific to this company/market', 'thresholds': {}}, {'sub_id': 'risk_coverage', 'description': 'Market, execution, and regulatory/ITAR risks all addressed', 'weight': 0.3, 'measurement': '1.0 if all 3 categories, 0.5 if 2, 0.0 if 1', 'thresholds': {}}, {'sub_id': 'mitigants', 'description': 'Each risk has a plausible mitigant or monitoring plan', 'weight': 0.3, 'measurement': '% of risks with stated mitigants', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'ITAR compliance burden limits sales velocity — mitigant: CTO has existing DSP-5/DSP-73 experience from Lockheed tenure'

**Fail Examples:**

- 'Risk: competition. Risk: market might not grow.'

---

### 5. memo_deal_terms

- **Category:** practicality
- **Description:** Deal terms are realistic and internally consistent
- **Pass Condition:** Pre-money valuation, round size, lead investor type, and use of funds. Values are stage-appropriate (Series A defense: $15-40M pre). Use of funds is specific (hiring, ITAR facility, production line).

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'completeness', 'description': 'Valuation, round size, ownership target stated', 'weight': 0.4, 'measurement': '% of deal terms present', 'thresholds': {}}, {'sub_id': 'stage_appropriateness', 'description': 'Values are realistic for Series A defense startup', 'weight': 0.3, 'measurement': '1.0 if realistic, 0.5 if slightly off, 0.0 if unrealistic', 'thresholds': {}}, {'sub_id': 'use_of_funds', 'description': 'Specific allocation of capital', 'weight': 0.3, 'measurement': '1.0 if specific breakdown, 0.5 if vague, 0.0 if absent', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- '$20M Series A at $60M pre. Use: 40% eng/autonomy, 25% ITAR facility, 20% BD, 15% ops'

**Fail Examples:**

- 'Raising a Series A at a good valuation'

---
