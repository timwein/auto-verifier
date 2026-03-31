# Rubric: billing_schema

**Task:** Design a JSON schema for a multi-tenant SaaS billing system supporting usage-based and seat-based pricing
**Domain:** schema_design
**Total Points:** 38
**Pass Threshold:** 0.85

## Criteria

### 1. schema_completeness

- **Category:** design
- **Description:** Schema covers all required entities and pricing models
- **Pass Condition:** Entities: tenant, plan, subscription, usage_record, invoice, line_item. Pricing models: per-seat, usage-based (metered), tiered, hybrid. Billing cycles, proration, trial periods.

**Scoring:**

- method: weighted_components
- max_points: 12
- sub_attributes: [{'sub_id': 'entity_coverage', 'description': 'All required entities present', 'weight': 0.3, 'measurement': '% of required entities modeled (tenant, plan, subscription, usage, invoice, line_item)', 'thresholds': {}}, {'sub_id': 'pricing_model_support', 'description': 'Both seat-based and usage-based modeled', 'weight': 0.35, 'measurement': '1.0 if both + hybrid, 0.75 if both, 0.5 if one, 0.0 if neither', 'thresholds': {}}, {'sub_id': 'billing_lifecycle', 'description': 'Cycles, proration, trials, upgrades/downgrades', 'weight': 0.35, 'measurement': '% of lifecycle events modeled (create, upgrade, downgrade, cancel, prorate, trial)', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Plan with pricing_model: {type: 'hybrid', seat_price: ..., metered_dimensions: [...]}

**Fail Examples:**

- Just 'plan' and 'subscription' with flat price field

---

### 2. schema_correctness

- **Category:** quality
- **Description:** Valid JSON Schema with proper types, constraints, references
- **Pass Condition:** Valid JSON Schema (draft-07+). Uses $ref for reuse. Required fields marked. Enums for constrained values. Proper date-time formats.

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'schema_validity', 'description': 'Valid JSON Schema syntax', 'weight': 0.3, 'measurement': '1.0 if valid draft-07+, 0.5 if mostly valid, 0.0 if invalid', 'thresholds': {}}, {'sub_id': 'ref_usage', 'description': 'Uses $ref for reusable definitions', 'weight': 0.25, 'measurement': '1.0 if DRY with $ref, 0.5 if some reuse, 0.0 if duplicated', 'thresholds': {}}, {'sub_id': 'constraint_quality', 'description': 'Proper enums, required, formats, patterns', 'weight': 0.45, 'measurement': '% of fields with appropriate constraints', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- $ref to shared 'money' type with currency+amount, enum for billing_interval

**Fail Examples:**

- Freeform JSON with no type constraints

---

### 3. schema_extensibility

- **Category:** architecture
- **Description:** Schema is extensible without breaking changes
- **Pass Condition:** Uses additionalProperties judiciously. Versioned. Metered dimensions are a list (not hardcoded). Custom metadata fields supported.

**Scoring:**

- method: weighted_components
- max_points: 8
- sub_attributes: [{'sub_id': 'metered_extensibility', 'description': 'Usage dimensions are dynamic, not hardcoded', 'weight': 0.4, 'measurement': '1.0 if array of dimension objects, 0.5 if a few named fields, 0.0 if hardcoded', 'thresholds': {}}, {'sub_id': 'metadata_support', 'description': 'Custom metadata/extension points', 'weight': 0.3, 'measurement': '1.0 if metadata object on key entities, 0.0 if closed', 'thresholds': {}}, {'sub_id': 'versioning', 'description': 'Schema version field or versioning strategy', 'weight': 0.3, 'measurement': '1.0 if versioned, 0.0 if not', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- metered_dimensions: [{id, unit, tiers: [...]}] — add new dimensions without schema change

**Fail Examples:**

- Hardcoded 'api_calls' and 'storage_gb' fields

---

### 4. schema_realworld

- **Category:** practicality
- **Description:** Schema reflects real billing system patterns (Stripe-informed, not academic)
- **Pass Condition:** Models concepts from real systems: idempotency keys, invoice status lifecycle, webhook events, currency handling. Avoids naive patterns (storing calculated totals without line items).

**Scoring:**

- method: penalty_based
- max_points: 8
- sub_attributes: []
- penalties: {'no_currency_handling': -2.0, 'calculated_total_without_line_items': -2.0, 'no_idempotency': -1.0, 'no_invoice_status_lifecycle': -1.5, 'naive_date_handling': -1.5, 'single_currency_assumption': -1.0}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Invoice with status enum (draft→open→paid→void), line_items array, currency code per amount

**Fail Examples:**

- Invoice with just 'total: 99.99' and no line items

---
