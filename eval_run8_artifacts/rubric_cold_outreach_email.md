# Rubric: cold_outreach_email

**Task:** Write a cold outreach email to a Series A founder pitching angel investment
**Domain:** cold_outreach_email
**Total Points:** 56
**Pass Threshold:** 0.8

## Criteria

### 1. email_subject

- **Category:** engagement
- **Description:** Subject line is compelling and specific — not generic or spammy
- **Pass Condition:** Subject is <60 chars, references something specific to the recipient, creates curiosity without clickbait. No 'Quick question' or 'Touching base'.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'specificity', 'description': "References recipient's company/round/domain", 'weight': 0.4, 'measurement': '1.0 if names company or specific context, 0.0 if generic', 'thresholds': {}}, {'sub_id': 'brevity', 'description': 'Under 60 chars, scannable on mobile', 'weight': 0.25, 'measurement': '1.0 if ≤60 chars, 0.5 if ≤80, 0.0 if >80', 'thresholds': {}}, {'sub_id': 'curiosity_hook', 'description': 'Creates reason to open without being clickbait', 'weight': 0.35, 'measurement': '1.0 if compelling + honest, 0.5 if generic, 0.0 if spammy', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- '$2M angel check for Acme's Series A — operator background in logistics'

**Fail Examples:**

- 'Quick question'
- 'Exciting investment opportunity!'

---

### 2. email_opening

- **Category:** engagement
- **Description:** First sentence earns the right to the second — no throat-clearing
- **Pass Condition:** Opens with specific signal: why now, why them, what you noticed. No 'I hope this finds you well' or self-introductions.

**Scoring:**

- method: penalty_based
- max_points: 8
- sub_attributes: []
- penalties: {'generic_greeting': -3.0, 'self_intro_first': -2.0, 'no_specific_signal': -2.0, 'too_long_opening': -1.5}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Saw your Techcrunch piece on [X] — the way you're attacking [problem] maps to what I built at [company]'

**Fail Examples:**

- 'Hi, my name is Tim and I'm an angel investor...'

---

### 3. email_value_prop

- **Category:** persuasion
- **Description:** Clearly articulates what the angel brings beyond capital
- **Pass Condition:** Specific operational value: domain expertise, network, customer intros, hiring help. Concrete, not vague ('I can help').

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'specificity', 'description': 'Names concrete value (intros, expertise, past wins)', 'weight': 0.45, 'measurement': '1.0 if 2+ specific offerings, 0.5 if 1 vague, 0.0 if just capital', 'thresholds': {}}, {'sub_id': 'relevance', 'description': "Value prop maps to recipient's actual needs/stage", 'weight': 0.35, 'measurement': '1.0 if clearly relevant to their domain/stage, 0.0 if generic', 'thresholds': {}}, {'sub_id': 'credibility', 'description': 'Claims are verifiable (named companies, outcomes)', 'weight': 0.2, 'measurement': '1.0 if verifiable claims, 0.5 if plausible, 0.0 if unsubstantiated', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'I scaled logistics ops from $5M to $80M ARR at ShipCo — happy to open my network of 20+ VP Supply Chain contacts'

**Fail Examples:**

- 'I bring smart capital and strategic value to my portfolio companies'

---

### 4. email_social_proof

- **Category:** credibility
- **Description:** Establishes credibility without bragging
- **Pass Condition:** 1-2 relevant proof points: portfolio wins, operating background, mutual connections. Woven in, not a resume dump.

**Scoring:**

- method: weighted_components
- max_points: 8
- sub_attributes: [{'sub_id': 'proof_quality', 'description': 'Proof points are relevant and impressive', 'weight': 0.5, 'measurement': '1.0 if directly relevant wins, 0.5 if tangential, 0.0 if absent', 'thresholds': {}}, {'sub_id': 'restraint', 'description': '1-2 points, not a resume dump', 'weight': 0.3, 'measurement': '1.0 if 1-2 tight proof points, 0.5 if 3-4, 0.0 if resume paragraph', 'thresholds': {}}, {'sub_id': 'natural_integration', 'description': 'Proof woven into narrative, not listed', 'weight': 0.2, 'measurement': '1.0 if organic, 0.0 if bullet-pointed credentials', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- '...when I was CTO at [X] (acq. by Google), we solved a similar cold-start problem'

**Fail Examples:**

- 'I have 15 years of experience, 30 investments, board seats at...'

---

### 5. email_cta

- **Category:** conversion
- **Description:** Call to action is low-friction and specific
- **Pass Condition:** Single, clear ask. Low commitment (15-min call, not 'let's meet'). Suggests specific times or next step.

**Scoring:**

- method: weighted_components
- max_points: 8
- sub_attributes: [{'sub_id': 'clarity', 'description': 'Single unambiguous ask', 'weight': 0.35, 'measurement': '1.0 if one clear ask, 0.5 if implied, 0.0 if multiple/confusing', 'thresholds': {}}, {'sub_id': 'low_friction', 'description': 'Minimal commitment required', 'weight': 0.35, 'measurement': '1.0 if 15-min call or async, 0.5 if meeting, 0.0 if big ask', 'thresholds': {}}, {'sub_id': 'specificity', 'description': 'Includes proposed time or concrete next step', 'weight': 0.3, 'measurement': "1.0 if specific availability, 0.5 if 'sometime this week', 0.0 if open-ended", 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 'Free for a 15-min call Thursday or Friday afternoon? Happy to share my thesis on [space] first over email if you prefer.'

**Fail Examples:**

- 'Let me know if you're interested in chatting sometime.'

---

### 6. email_tone

- **Category:** voice
- **Description:** Tone is peer-to-peer, confident but not presumptuous
- **Pass Condition:** Reads like one founder talking to another. Not sycophantic, not salesy, not formal. Respects their time.

**Scoring:**

- method: penalty_based
- max_points: 6
- sub_attributes: []
- penalties: {'sycophantic_language': -2.0, 'salesy_pressure': -2.0, 'overly_formal': -1.5, 'presumptuous_familiarity': -1.5, 'humble_brag': -1.0}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Direct, warm, brief — reads like a text from a smart friend

**Fail Examples:**

- 'I'd be truly honored to be part of your incredible journey'

---

### 7. email_length

- **Category:** structure
- **Description:** Email is scannable in <30 seconds — under 150 words
- **Pass Condition:** Under 150 words. Short paragraphs (1-3 sentences). White space between blocks. No walls of text.

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'word_count', 'description': 'Under 150 words total', 'weight': 0.5, 'measurement': '1.0 if ≤150, 0.7 if ≤200, 0.3 if ≤250, 0.0 if >250', 'thresholds': {}}, {'sub_id': 'scannability', 'description': 'Short paragraphs, visual breaks', 'weight': 0.5, 'measurement': '1.0 if all paragraphs ≤3 sentences with breaks, 0.0 if wall of text', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- 5 short paragraphs, 120 words total

**Fail Examples:**

- 3 dense paragraphs, 300+ words

---
