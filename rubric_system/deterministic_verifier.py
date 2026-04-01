#!/usr/bin/env python3
"""
DeterministicVerifier — Programmatic scoring for objectively checkable criteria.

Detects rubric criteria that can be verified without LLM judgment and routes
them to exact code-based checks instead. Eliminates LLM scoring noise on
criteria like word count, format compliance, code syntax, and section presence.

Detection is general-purpose: pattern matching on criterion text fields
(description, pass_condition, sub-attribute descriptions/measurements), not
hardcoded criterion IDs. Works for any rubric on any task.

Python 3.9 compatible. No external dependencies beyond stdlib (ast, re).
"""

import ast
import re
from typing import Optional

from rubric_system.models import Criterion, CriterionScore


# ============================================================================
# Compiled detection patterns
# ============================================================================

# Word count — max constraint: "under X words", "no more than X words", etc.
_WC_MAX = re.compile(
    r'(?:under|no more than|at most|fewer than|less than)\s+([\d,]+)\s+words?',
    re.IGNORECASE,
)
# Word count — min constraint: "at least X words", "minimum X words", etc.
_WC_MIN = re.compile(
    r'(?:at least|minimum of?|no fewer than)\s+([\d,]+)\s+words?',
    re.IGNORECASE,
)
# Word count — range: "between X and Y words" OR "X-Y words"
_WC_RANGE = re.compile(
    r'(?:between\s+([\d,]+)\s+and\s+([\d,]+)\s+words?'
    r'|([\d,]+)\s*[-\u2013\u2014]\s*([\d,]+)\s+words?)',
    re.IGNORECASE,
)
# Word count — approximate: "approximately X words", "~X words"
_WC_APPROX = re.compile(
    r'(?:approximately|roughly|around|~)\s*([\d,]+)\s+words?',
    re.IGNORECASE,
)

# Character count
_CC_MAX = re.compile(
    r'(?:under|no more than|at most|fewer than|less than)\s+([\d,]+)\s+characters?',
    re.IGNORECASE,
)
_CC_MIN = re.compile(
    r'(?:at least|minimum of?|no fewer than)\s+([\d,]+)\s+characters?',
    re.IGNORECASE,
)

# Item/list count — "at least N items/examples/bullet points/..."
_IC_AT_LEAST = re.compile(
    r'(?:at least|minimum of?|no fewer than)\s+([\d,]+)\s+'
    r'(?:items?|examples?|bullet\s*points?|points?|reasons?|recommendations?'
    r'|steps?|sections?|factors?|criteria|requirements?|topics?|tips?)',
    re.IGNORECASE,
)
_IC_EXACTLY = re.compile(
    r'(?:exactly|precisely)\s+([\d,]+)\s+'
    r'(?:items?|examples?|bullet\s*points?|points?|reasons?|recommendations?'
    r'|steps?|sections?|factors?|criteria|requirements?|topics?|tips?)',
    re.IGNORECASE,
)
_IC_OR_MORE = re.compile(
    r'([\d,]+)\s+or\s+more\s+'
    r'(?:items?|examples?|bullet\s*points?|points?|reasons?|recommendations?'
    r'|steps?|sections?|factors?|criteria|requirements?|topics?|tips?)',
    re.IGNORECASE,
)

# Format / structure presence patterns
_HAS_CODE_BLOCKS = re.compile(
    r'\b(?:includes?|contains?|has|show|provide|use)\b.{0,30}'
    r'\b(?:code\s+blocks?|code\s+examples?|code\s+snippets?|fenced\s+code'
    r'|python\s+code|executable\s+code)\b',
    re.IGNORECASE,
)
_HAS_HEADERS = re.compile(
    r'\b(?:includes?|contains?|has|organized\s+into|divided\s+into'
    r'|structured\s+with)\b.{0,40}'
    r'\b(?:headers?|headings?|sections?|subsections?)\b',
    re.IGNORECASE,
)
_HAS_BULLETS = re.compile(
    r'\b(?:includes?|contains?|has|uses?|formatted\s+as|presented\s+as'
    r'|organized\s+as)\b.{0,40}'
    r'\b(?:bullet\s+points?|bulleted\s+list|bullets?|unordered\s+list)\b',
    re.IGNORECASE,
)
_HAS_TITLE = re.compile(
    r'\b(?:includes?|contains?|has|starts?\s+with|begins?\s+with'
    r'|opens?\s+with)\b.{0,20}\b(?:title|heading|h1)\b',
    re.IGNORECASE,
)
_HAS_NUMBERED_LIST = re.compile(
    r'\b(?:uses?|includes?|presents?|has)\b.{0,30}'
    r'\b(?:numbered\s+list|ordered\s+list|numbered\s+items?)\b',
    re.IGNORECASE,
)
_HAS_TABLE = re.compile(
    r'\b(?:includes?|contains?|has|presents?)\b.{0,30}'
    r'\b(?:table|tabular|grid)\b',
    re.IGNORECASE,
)

# Python code syntax validity
_VALID_PYTHON = re.compile(
    r'(?:\b(?:valid|syntactically\s+correct|runnable|compilable|executable'
    r'|working)\b.{0,30}\b(?:python|python3?)\b'
    r'|\bpython\b.{0,30}\b(?:valid|syntax|compilable|correct|runnable)\b)',
    re.IGNORECASE,
)

# Required section presence
_HAS_INTRO = re.compile(
    r'\b(?:includes?|has|contains?|begins?\s+with)\b.{0,20}'
    r'\b(?:introduction|intro)\b',
    re.IGNORECASE,
)
_HAS_CONCLUSION = re.compile(
    r'\b(?:includes?|has|contains?|ends?\s+with)\b.{0,20}'
    r'\b(?:conclusion|summary|closing)\b',
    re.IGNORECASE,
)
_HAS_ABSTRACT = re.compile(
    r'\b(?:includes?|has|contains?)\b.{0,20}'
    r'\b(?:abstract|executive\s+summary)\b',
    re.IGNORECASE,
)

# Bash safety patterns
_BASH_SET_EUO = re.compile(r'\bset\s+-euo\s+pipefail\b')
_BASH_SET_E = re.compile(r'\bset\s+-[A-Za-z]*e[A-Za-z]*\b')
_BASH_PIPEFAIL = re.compile(r'\bset\s+-o\s+pipefail\b')
_BASH_TRAP = re.compile(r'\btrap\b.+\b(?:EXIT|ERR|SIGTERM|SIGINT)\b')
_HARDCODED_PASSWORD = re.compile(
    r'\b(?:PASSWORD|PASSWD|DB_PASS|PGPASSWORD)\s*=\s*[\x27"][^$]',
    re.IGNORECASE,
)

# SQL anti-patterns
_SQL_SELECT_STAR = re.compile(r'\bSELECT\s+\*\s+FROM\b', re.IGNORECASE)

# Criterion detection — is this a bash safety criterion?
_IS_BASH_SAFETY = re.compile(
    r'\b(?:set\s+-e|pipefail|trap|hardcoded\s+password|bash\s+safety'
    r'|error\s+handling\s+flags)\b',
    re.IGNORECASE,
)

# Criterion detection — is this a SQL performance/quality criterion?
# Note: trailing \b omitted because \* is non-word; \b before SELECT suffices.
_IS_SQL_CRITERION = re.compile(
    r'\bSELECT\s+\*'
    r'|\bsql\s+performance\b'
    r'|\bsql\s+anti.?pattern'
    r'|\bavoid(?:s)?\s+SELECT\s+\*'
    r'|\bquery\s+optimization\b',
    re.IGNORECASE,
)


# ============================================================================
# Content measurement utilities
# ============================================================================

def _parse_int(s: str) -> int:
    """Parse integer from string that may contain commas (e.g. '1,000')."""
    return int(s.replace(',', ''))


def _count_words(text: str) -> int:
    """Count whitespace-separated tokens."""
    return len(text.split())


def _count_list_items(content: str) -> int:
    """Count bullet points and numbered list items."""
    count = 0
    for line in content.split('\n'):
        stripped = line.strip()
        if re.match(r'^[-*\u2022]\s+\S', stripped):   # unordered: -, *, •
            count += 1
        elif re.match(r'^\d+[.)]\s+\S', stripped):    # ordered: 1. or 1)
            count += 1
    return count


def _count_headers(content: str) -> int:
    """Count markdown headers (# through ######)."""
    return len(re.findall(r'^#{1,6}\s+\S', content, re.MULTILINE))


def _has_code_block(content: str) -> bool:
    """Check for fenced (```) or indented (4-space/tab) code blocks."""
    if '```' in content:
        return True
    if re.search(r'^(?:    |\t)\S', content, re.MULTILINE):
        return True
    return False


def _has_bullet_points(content: str) -> bool:
    return bool(re.search(r'^[-*\u2022]\s+\S', content, re.MULTILINE))


def _has_numbered_list(content: str) -> bool:
    return bool(re.search(r'^\d+[.)]\s+\S', content, re.MULTILINE))


def _has_headers(content: str) -> bool:
    return bool(re.search(r'^#{1,6}\s+\S', content, re.MULTILINE))


def _has_title(content: str) -> bool:
    """Check if content starts with a markdown H1 or bold first line."""
    lines = [l for l in content.split('\n') if l.strip()]
    if not lines:
        return False
    first = lines[0].strip()
    if re.match(r'^#\s+\S', first):            # # Title
        return True
    if re.match(r'^\*\*.+\*\*\s*$', first):   # **Title**
        return True
    if re.match(r'^__.+__\s*$', first):        # __Title__
        return True
    return False


def _has_table(content: str) -> bool:
    """Check for markdown pipe tables."""
    return bool(re.search(r'^\|.+\|', content, re.MULTILINE))


def _extract_python_blocks(content: str) -> list:
    """Extract source from ```python ... ``` and ``` ... ``` fenced blocks."""
    blocks = []
    for m in re.finditer(r'```(?:python|py)?\n(.*?)```', content, re.DOTALL):
        blocks.append(m.group(1))
    return blocks


def _has_section(content: str, keyword: str) -> bool:
    """Check if content contains a named section (header or bold paragraph start)."""
    # Markdown header: # Introduction, ## Conclusion, etc.
    if re.search(
        r'^#{1,6}\s+.*\b' + re.escape(keyword) + r'\b',
        content, re.MULTILINE | re.IGNORECASE,
    ):
        return True
    # Bold paragraph header: **Introduction** or **Conclusion**
    if re.search(
        r'^\*\*.*\b' + re.escape(keyword) + r'\b.*\*\*',
        content, re.MULTILINE | re.IGNORECASE,
    ):
        return True
    # Keyword starting a paragraph (after blank line)
    if re.search(
        r'(?:^|\n\n)' + re.escape(keyword) + r'[:\s]',
        content, re.IGNORECASE,
    ):
        return True
    return False


# ============================================================================
# DeterministicVerifier
# ============================================================================

class DeterministicVerifier:
    """
    Routes objectively checkable rubric criteria to code-based verification.

    For each criterion, uses pattern matching on the criterion's text fields
    (description, pass_condition, sub-attribute descriptions and measurements)
    to detect if the criterion is programmatically verifiable. Returns a
    CriterionScore for verifiable criteria, None for criteria requiring LLM
    judgment.

    Detection is conservative: only claims verifiability when the pattern
    match is unambiguous and the programmatic check is known to be accurate.
    Scores are exact — no LLM noise.

    Supported check types (in confidence order):
      1. Word count  — under/at-least/between/approx X words
      2. Char count  — under/at-least X characters
      3. Item count  — at-least/exactly/N-or-more list items/examples/...
      4. Python syntax — valid/compilable Python code (ast.parse)
      5. Code blocks — includes/has code blocks/examples
      6. Headers     — organized into sections / has headers
      7. Bullet points — uses bullet points / bulleted list
      8. Numbered list — uses numbered list / ordered list
      9. Title       — includes a title / starts with heading
     10. Table       — includes a table / tabular data
     11. Sections    — includes introduction / conclusion / abstract
    """

    def verify_criterion(
        self, criterion: Criterion, content: str
    ) -> Optional[CriterionScore]:
        """
        Attempt deterministic verification of a criterion.

        Returns CriterionScore if the criterion is programmatically checkable,
        None if LLM judgment is required.

        Args:
            criterion: The rubric criterion to verify.
            content:   The generated content to check.
        """
        search_text = self._criterion_text(criterion)

        for checker in (
            self._check_word_count,
            self._check_char_count,
            self._check_item_count,
            self._check_code_syntax,
            self._check_has_code_blocks,
            self._check_has_headers,
            self._check_has_bullet_points,
            self._check_has_numbered_list,
            self._check_has_title,
            self._check_has_table,
            self._check_section_presence,
            self._check_bash_safety,
            self._check_sql_patterns,
        ):
            result = checker(criterion, search_text, content)
            if result is not None:
                return result

        return None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _criterion_text(self, criterion: Criterion) -> str:
        """Combine all text fields for detection."""
        parts = [criterion.description, criterion.pass_condition]
        for sub in criterion.scoring.sub_attributes:
            parts.append(sub.description)
            parts.append(sub.measurement)
        return " ".join(p for p in parts if p)

    def _make_score(
        self,
        criterion: Criterion,
        percentage: float,
        evidence: str,
        methodology: str,
    ) -> CriterionScore:
        """Build a CriterionScore from a deterministic check result."""
        percentage = max(0.0, min(1.0, percentage))
        points = round(criterion.scoring.max_points * percentage, 2)
        return CriterionScore(
            criterion_id=criterion.id,
            points_earned=points,
            max_points=criterion.scoring.max_points,
            percentage=percentage,
            evidence=evidence,
            methodology=f"Deterministic: {methodology}",
        )

    # -------------------------------------------------------------------------
    # Checkers
    # -------------------------------------------------------------------------

    def _check_word_count(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Verify word count constraints."""
        wc = _count_words(content)

        # Max: "under X words", "no more than X words", "at most X words"
        m = _WC_MAX.search(text)
        if m:
            limit = _parse_int(m.group(1))
            pct = 1.0 if wc <= limit else limit / wc
            indicator = "✓" if wc <= limit else "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"Word count: {wc:,} (target: ≤{limit:,}) {indicator}",
                methodology="word count ≤ max",
            )

        # Min: "at least X words", "minimum X words"
        m = _WC_MIN.search(text)
        if m:
            floor = _parse_int(m.group(1))
            pct = 1.0 if wc >= floor else wc / floor
            indicator = "✓" if wc >= floor else "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"Word count: {wc:,} (target: ≥{floor:,}) {indicator}",
                methodology="word count ≥ min",
            )

        # Range: "between X and Y words" or "X-Y words"
        m = _WC_RANGE.search(text)
        if m:
            if m.group(1):   # "between X and Y words"
                lo, hi = _parse_int(m.group(1)), _parse_int(m.group(2))
            else:            # "X-Y words"
                lo, hi = _parse_int(m.group(3)), _parse_int(m.group(4))
            if lo <= wc <= hi:
                pct, indicator = 1.0, "✓"
            elif wc < lo:
                pct, indicator = wc / lo, "✗"
            else:
                pct, indicator = hi / wc, "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"Word count: {wc:,} (target: {lo:,}–{hi:,}) {indicator}",
                methodology="word count in range",
            )

        # Approx: "approximately X words", "~X words"
        m = _WC_APPROX.search(text)
        if m:
            target = _parse_int(m.group(1))
            lo = int(target * 0.80)
            hi = int(target * 1.20)
            if lo <= wc <= hi:
                pct, indicator = 1.0, "✓"
            elif wc < lo:
                pct, indicator = wc / lo, "✗"
            else:
                pct, indicator = hi / wc, "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"Word count: {wc:,} (target: ~{target:,} ±20%) {indicator}",
                methodology="word count ≈ target (±20%)",
            )

        return None

    def _check_char_count(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Verify character count constraints."""
        cc = len(content)

        m = _CC_MAX.search(text)
        if m:
            limit = _parse_int(m.group(1))
            pct = 1.0 if cc <= limit else limit / cc
            indicator = "✓" if cc <= limit else "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"Character count: {cc:,} (target: ≤{limit:,}) {indicator}",
                methodology="character count ≤ max",
            )

        m = _CC_MIN.search(text)
        if m:
            floor = _parse_int(m.group(1))
            pct = 1.0 if cc >= floor else cc / floor
            indicator = "✓" if cc >= floor else "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"Character count: {cc:,} (target: ≥{floor:,}) {indicator}",
                methodology="character count ≥ min",
            )

        return None

    def _check_item_count(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Verify list item count constraints."""
        item_count = _count_list_items(content)

        # "at least N" or "N or more"
        for pattern in (_IC_AT_LEAST, _IC_OR_MORE):
            m = pattern.search(text)
            if m:
                required = _parse_int(m.group(1))
                if required == 0:
                    return None
                pct = 1.0 if item_count >= required else item_count / required
                indicator = "✓" if item_count >= required else "✗"
                return self._make_score(
                    criterion, pct,
                    evidence=f"List items: {item_count} (target: ≥{required}) {indicator}",
                    methodology="list item count ≥ min",
                )

        # "exactly N"
        m = _IC_EXACTLY.search(text)
        if m:
            required = _parse_int(m.group(1))
            if required == 0:
                return None
            if item_count == required:
                pct, indicator = 1.0, "✓"
            else:
                pct = 1.0 - min(abs(item_count - required) / required, 1.0)
                indicator = "✗"
            return self._make_score(
                criterion, pct,
                evidence=f"List items: {item_count} (target: exactly {required}) {indicator}",
                methodology="list item count = exact",
            )

        return None

    def _check_code_syntax(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Verify Python code syntax using ast.parse (stdlib only)."""
        if not _VALID_PYTHON.search(text):
            return None

        blocks = _extract_python_blocks(content)
        if not blocks:
            return self._make_score(
                criterion, 0.0,
                evidence="No Python code blocks found in content ✗",
                methodology="Python syntax check (ast.parse)",
            )

        errors = []
        for i, block in enumerate(blocks, 1):
            try:
                ast.parse(block)
            except SyntaxError as e:
                errors.append(f"block {i}: {e.msg} (line {e.lineno})")

        if not errors:
            return self._make_score(
                criterion, 1.0,
                evidence=f"{len(blocks)} Python code block(s) parsed successfully ✓",
                methodology="Python syntax check (ast.parse)",
            )

        pct = (len(blocks) - len(errors)) / len(blocks)
        return self._make_score(
            criterion, pct,
            evidence=(
                f"{len(errors)}/{len(blocks)} Python block(s) have syntax errors: "
                + "; ".join(errors[:2]) + " ✗"
            ),
            methodology="Python syntax check (ast.parse)",
        )

    def _check_has_code_blocks(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        if not _HAS_CODE_BLOCKS.search(text):
            return None
        present = _has_code_block(content)
        pct = 1.0 if present else 0.0
        indicator = "✓" if present else "✗"
        return self._make_score(
            criterion, pct,
            evidence=f"Code blocks: {'present' if present else 'not found'} {indicator}",
            methodology="code block presence check",
        )

    def _check_has_headers(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        if not _HAS_HEADERS.search(text):
            return None
        count = _count_headers(content)
        pct = 1.0 if count > 0 else 0.0
        indicator = "✓" if count > 0 else "✗"
        return self._make_score(
            criterion, pct,
            evidence=f"Headers: {count} found {indicator}",
            methodology="markdown header presence check",
        )

    def _check_has_bullet_points(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        if not _HAS_BULLETS.search(text):
            return None
        present = _has_bullet_points(content)
        pct = 1.0 if present else 0.0
        indicator = "✓" if present else "✗"
        return self._make_score(
            criterion, pct,
            evidence=f"Bullet points: {'present' if present else 'not found'} {indicator}",
            methodology="bullet point presence check",
        )

    def _check_has_numbered_list(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        if not _HAS_NUMBERED_LIST.search(text):
            return None
        present = _has_numbered_list(content)
        pct = 1.0 if present else 0.0
        indicator = "✓" if present else "✗"
        return self._make_score(
            criterion, pct,
            evidence=f"Numbered list: {'present' if present else 'not found'} {indicator}",
            methodology="numbered list presence check",
        )

    def _check_has_title(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        if not _HAS_TITLE.search(text):
            return None
        present = _has_title(content)
        pct = 1.0 if present else 0.0
        indicator = "✓" if present else "✗"
        return self._make_score(
            criterion, pct,
            evidence=f"Title: {'present' if present else 'not found'} {indicator}",
            methodology="title presence check",
        )

    def _check_has_table(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        if not _HAS_TABLE.search(text):
            return None
        present = _has_table(content)
        pct = 1.0 if present else 0.0
        indicator = "✓" if present else "✗"
        return self._make_score(
            criterion, pct,
            evidence=f"Table: {'present' if present else 'not found'} {indicator}",
            methodology="table presence check",
        )

    def _check_bash_safety(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Verify bash safety practices via regex (penalty-based)."""
        if criterion.scoring.method.value != "penalty_based":
            return None
        if not _IS_BASH_SAFETY.search(text):
            return None

        penalties = criterion.scoring.penalties
        max_points = criterion.scoring.max_points
        findings = []
        total_deduction = 0.0

        # Check for set -e (covers set -euo as well)
        if "no_set_e" in penalties and not _BASH_SET_E.search(content):
            total_deduction += abs(penalties["no_set_e"])
            findings.append("no set -e")

        # Check for pipefail (set -o pipefail OR set -euo pipefail)
        if "no_pipefail" in penalties:
            if not _BASH_PIPEFAIL.search(content) and not _BASH_SET_EUO.search(content):
                total_deduction += abs(penalties["no_pipefail"])
                findings.append("no pipefail")

        # Check for trap cleanup
        if "no_trap_cleanup" in penalties and not _BASH_TRAP.search(content):
            total_deduction += abs(penalties["no_trap_cleanup"])
            findings.append("no trap cleanup")

        # Check for hardcoded passwords
        if "hardcoded_password" in penalties and _HARDCODED_PASSWORD.search(content):
            total_deduction += abs(penalties["hardcoded_password"])
            findings.append("hardcoded password")

        score = max(0.0, max_points - total_deduction)
        pct = score / max_points if max_points > 0 else 0.0

        if findings:
            evidence = f"Bash safety issues: {', '.join(findings)} (−{total_deduction:.1f} pts) ✗"
        else:
            evidence = "Bash safety checks passed: set -e, pipefail, trap, no hardcoded passwords ✓"

        return self._make_score(
            criterion, pct,
            evidence=evidence,
            methodology=f"bash safety regex check ({max_points} − {total_deduction:.1f} = {score:.1f})",
        )

    def _check_sql_patterns(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Verify SQL anti-pattern avoidance via regex (penalty-based)."""
        if criterion.scoring.method.value != "penalty_based":
            return None
        if not _IS_SQL_CRITERION.search(text):
            return None

        penalties = criterion.scoring.penalties
        max_points = criterion.scoring.max_points
        findings = []
        total_deduction = 0.0

        # Check for SELECT *
        if "select_star" in penalties and _SQL_SELECT_STAR.search(content):
            total_deduction += abs(penalties["select_star"])
            findings.append("SELECT * usage")

        score = max(0.0, max_points - total_deduction)
        pct = score / max_points if max_points > 0 else 0.0

        if findings:
            evidence = f"SQL issues: {', '.join(findings)} (−{total_deduction:.1f} pts) ✗"
        else:
            evidence = "SQL pattern checks passed: no SELECT * ✓"

        return self._make_score(
            criterion, pct,
            evidence=evidence,
            methodology=f"SQL pattern regex check ({max_points} − {total_deduction:.1f} = {score:.1f})",
        )

    def _check_section_presence(
        self, criterion: Criterion, text: str, content: str
    ) -> Optional[CriterionScore]:
        """Check for required named sections (introduction, conclusion, abstract)."""
        checks = []  # [(label, found)]

        if _HAS_INTRO.search(text):
            found = _has_section(content, "introduction") or _has_section(content, "intro")
            checks.append(("introduction", found))

        if _HAS_CONCLUSION.search(text):
            found = (
                _has_section(content, "conclusion")
                or _has_section(content, "summary")
                or _has_section(content, "closing")
            )
            checks.append(("conclusion", found))

        if _HAS_ABSTRACT.search(text):
            found = (
                _has_section(content, "abstract")
                or _has_section(content, "executive summary")
            )
            checks.append(("abstract", found))

        if not checks:
            return None

        pct = sum(1 for _, found in checks if found) / len(checks)
        parts = [f"{name}: {'✓' if found else '✗'}" for name, found in checks]
        return self._make_score(
            criterion, pct,
            evidence="Required sections — " + ", ".join(parts),
            methodology="required section presence check",
        )
