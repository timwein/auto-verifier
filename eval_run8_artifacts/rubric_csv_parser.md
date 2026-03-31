# Rubric: csv_parser

**Task:** Generate a Python function that parses messy CSV data with inconsistent delimiters and missing headers
**Domain:** code_generation
**Total Points:** 44
**Pass Threshold:** 0.85

## Criteria

### 1. code_correctness

- **Category:** functionality
- **Description:** Function handles the stated requirements: inconsistent delimiters, missing headers
- **Pass Condition:** Detects and handles comma/tab/pipe/semicolon delimiters. Generates synthetic headers when missing. Doesn't crash on edge cases.

**Scoring:**

- method: weighted_components
- max_points: 12
- sub_attributes: [{'sub_id': 'delimiter_detection', 'description': 'Auto-detects or handles multiple delimiter types', 'weight': 0.35, 'measurement': '1.0 if auto-detects from data, 0.5 if parameterized, 0.0 if hardcoded', 'thresholds': {}}, {'sub_id': 'header_handling', 'description': 'Generates headers when missing, detects when present', 'weight': 0.35, 'measurement': '1.0 if auto-detects + generates, 0.5 if one or other, 0.0 if assumes headers', 'thresholds': {}}, {'sub_id': 'edge_case_resilience', 'description': 'Handles empty rows, mixed quoting, trailing delimiters', 'weight': 0.3, 'measurement': '% of edge cases handled without crash', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Uses csv.Sniffer for delimiter detection, heuristic for header presence

**Fail Examples:**

- Hardcodes comma delimiter, assumes first row is header

---

### 2. code_robustness

- **Category:** reliability
- **Description:** Graceful error handling, doesn't silently corrupt data
- **Pass Condition:** Try/except with meaningful errors. Logs warnings for skipped rows. Returns structured result with metadata (rows parsed, rows skipped, issues found).

**Scoring:**

- method: weighted_components
- max_points: 10
- sub_attributes: [{'sub_id': 'error_handling', 'description': 'Catches and reports errors meaningfully', 'weight': 0.4, 'measurement': '1.0 if structured error reporting, 0.5 if basic try/except, 0.0 if bare', 'thresholds': {}}, {'sub_id': 'data_integrity', 'description': 'Never silently drops or corrupts data', 'weight': 0.35, 'measurement': '1.0 if reports all anomalies, 0.0 if silently swallows', 'thresholds': {}}, {'sub_id': 'return_metadata', 'description': 'Returns parse stats (rows, skips, warnings)', 'weight': 0.25, 'measurement': '1.0 if structured result object, 0.5 if just data, 0.0 if raw list', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Returns ParseResult(data=..., warnings=[...], rows_skipped=2)

**Fail Examples:**

- Bare except: pass, returns partial data silently

---

### 3. code_api_design

- **Category:** usability
- **Description:** Function signature is clean, well-typed, with sensible defaults
- **Pass Condition:** Type hints. Docstring with examples. Reasonable defaults. Accepts str | Path | IO. Returns typed structure (not raw list).

**Scoring:**

- method: weighted_components
- max_points: 8
- sub_attributes: [{'sub_id': 'type_hints', 'description': 'Full type annotations on params and return', 'weight': 0.35, 'measurement': '1.0 if complete, 0.5 if partial, 0.0 if none', 'thresholds': {}}, {'sub_id': 'docstring', 'description': 'Docstring with description, args, returns, example', 'weight': 0.3, 'measurement': '1.0 if complete with example, 0.5 if basic, 0.0 if missing', 'thresholds': {}}, {'sub_id': 'input_flexibility', 'description': 'Accepts file path, string, or file object', 'weight': 0.35, 'measurement': '1.0 if multiple input types, 0.5 if one type, 0.0 if unclear', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- def parse_csv(source: str | Path | IO, ...) -> ParseResult:

**Fail Examples:**

- def parse(f):  # no types, no docs

---

### 4. code_idiomaticness

- **Category:** quality
- **Description:** Uses Python idioms and stdlib appropriately
- **Pass Condition:** Uses csv module (not regex-only). Leverages csv.Sniffer. Dataclasses or TypedDict for results. No reinventing wheels.

**Scoring:**

- method: penalty_based
- max_points: 8
- sub_attributes: []
- penalties: {'reinvents_csv_module': -3.0, 'regex_only_parsing': -2.0, 'no_type_structures': -1.5, 'mutable_default_args': -1.5, 'global_state': -2.0}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Builds on csv.reader/csv.Sniffer, returns dataclass

**Fail Examples:**

- Regex-only CSV parsing, returns list of dicts with no structure

---

### 5. code_testability

- **Category:** quality
- **Description:** Code is structured for easy testing
- **Pass Condition:** Pure function (no side effects). Includes or suggests test cases. Small composable helpers, not one monolith.

**Scoring:**

- method: weighted_components
- max_points: 6
- sub_attributes: [{'sub_id': 'pure_function', 'description': 'No side effects, deterministic', 'weight': 0.4, 'measurement': '1.0 if pure, 0.5 if minor side effects (logging ok), 0.0 if writes files', 'thresholds': {}}, {'sub_id': 'modularity', 'description': 'Logic decomposed into testable helpers', 'weight': 0.3, 'measurement': '1.0 if 3+ focused helpers, 0.5 if 2, 0.0 if monolith', 'thresholds': {}}, {'sub_id': 'test_examples', 'description': 'Includes example test cases or assertions', 'weight': 0.3, 'measurement': '1.0 if test cases included, 0.5 if doctest, 0.0 if none', 'thresholds': {}}]
- penalties: {}
- tiers: {}
- points_per_instance: 1.0
- max_instances: 10

**Source:** generated

**Pass Examples:**

- Separate detect_delimiter(), detect_headers(), parse_rows() + tests

**Fail Examples:**

- Single 80-line function with no tests

---
