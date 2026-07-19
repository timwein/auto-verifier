"""Executable gold for the csv_parser task (DESIGN_NOTES.md deviation 1).

The gold is: extract the candidate's ```python block, run it in a subprocess
against fixed messy-CSV fixtures, and compare the parsed output exactly
against pinned expected values. The prompt pins the function signature and
every parsing rule, so exact comparison is fair. Expected values are
hand-written in this file; sanity_check() asserts the reference
implementation reproduces them (spec section 9: spot-check the gold).

Authoring discipline: gold-only module. proxy_bank.py keeps its own fixture
set and must not import from here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

TASK_PROMPT = """Write a Python function that parses messy CSV text with inconsistent
delimiters. Exact contract:

    def parse_csv(text: str) -> list[list[str]]

Rules (all pinned — implement exactly these):

1. Delimiter detection: count raw occurrences of ',', ';', and '\\t' in the
   first non-empty line. The most frequent one is the delimiter; break ties by
   preferring ',' over ';' over '\\t'. If none occurs, the delimiter is ','.
2. Fields may be wrapped in double quotes. Inside a quoted field, the
   delimiter and newlines are literal field content, and a doubled quote ""
   is an escaped double-quote character.
3. Unquoted fields are stripped of leading/trailing spaces and tabs. Quoted
   field content is preserved verbatim (no stripping inside the quotes);
   whitespace between the quotes and the delimiter is ignored.
4. Rows whose entire line is empty or only whitespace (outside any quoted
   field) are skipped.
5. Rows may have different numbers of fields; return them as-is (no header
   handling, no padding).

Return only the code, in a single ```python fenced code block. The function
must be self-contained (stdlib only) and must be named parse_csv."""

REFERENCE_OUTPUT = '''```python
def parse_csv(text: str) -> list[list[str]]:
    """Parse messy CSV per the pinned contract: delimiter detection on the
    first non-empty line, double-quote fields with "" escapes, stripping of
    unquoted fields, whitespace-only lines skipped."""
    # --- delimiter detection (rule 1) ---
    delimiter = ","
    for line in text.split("\\n"):
        if line.strip():
            counts = [(line.count(","), ","), (line.count(";"), ";"),
                      (line.count("\\t"), "\\t")]
            best = max(c for c, _ in counts)
            if best > 0:
                for c, d in counts:  # tie-break: ',' > ';' > '\\t'
                    if c == best:
                        delimiter = d
                        break
            break

    rows: list[list[str]] = []
    field_chars: list[str] = []
    row: list[str] = []
    was_quoted = False
    in_quotes = False
    row_started = False
    i = 0
    n = len(text)

    def end_field() -> None:
        nonlocal field_chars, was_quoted
        raw = "".join(field_chars)
        row.append(raw if was_quoted else raw.strip(" \\t"))
        field_chars = []
        was_quoted = False

    def end_row() -> None:
        nonlocal row, row_started
        end_field()
        # rule 4: skip rows that are entirely whitespace
        if any(f != "" for f in row) or len(row) > 1:
            rows.append(row)
        row = []
        row_started = False

    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field_chars.append('"')
                    i += 2
                    continue
                in_quotes = False
            else:
                field_chars.append(ch)
            i += 1
            continue
        if ch == '"' and "".join(field_chars).strip(" \\t") == "":
            field_chars = []
            in_quotes = True
            was_quoted = True
            row_started = True
            i += 1
            continue
        if ch == delimiter:
            end_field()
            row_started = True
            i += 1
            continue
        if ch == "\\n":
            if row_started or "".join(field_chars).strip(" \\t") != "":
                end_row()
            else:
                field_chars = []
            i += 1
            continue
        if ch == "\\r":
            i += 1
            continue
        if was_quoted and ch in " \\t":
            i += 1  # rule 3: whitespace between closing quote and delimiter
            continue
        field_chars.append(ch)
        row_started = row_started or ch.strip(" \\t") != ""
        i += 1

    if row_started or "".join(field_chars).strip(" \\t") != "":
        end_row()
    return rows
```'''

# label -> (input text, expected parse). Expected values are hand-written;
# sanity_check() asserts the reference implementation reproduces them.
FIXTURES: dict[str, tuple[str, list[list[str]]]] = {
    "simple_comma": ("a,b,c\n1,2,3\n", [["a", "b", "c"], ["1", "2", "3"]]),
    "semicolon": ("x;y;z\n1;2;3\n", [["x", "y", "z"], ["1", "2", "3"]]),
    "tab": ("a\tb\n1\t2\n", [["a", "b"], ["1", "2"]]),
    "tie_prefers_comma": ("a,b;c\n1,2;3\n", [["a", "b;c"], ["1", "2;3"]]),
    "quoted_delimiter_and_escape": (
        'name,notes\n"Smith, John","said ""hi"""\n',
        [["name", "notes"], ["Smith, John", 'said "hi"']],
    ),
    "whitespace_stripping": (
        '  a  , b ,c  \n " kept " ,d\n',
        [["a", "b", "c"], [" kept ", "d"]],
    ),
    "empty_lines_skipped": ("a,b\n\n   \n1,2\n", [["a", "b"], ["1", "2"]]),
    "embedded_newline": (
        'a,b\n"line1\nline2",x\n',
        [["a", "b"], ["line1\nline2", "x"]],
    ),
    "ragged_rows": ("a,b,c\n1,2\n", [["a", "b", "c"], ["1", "2"]]),
    "no_delimiter_single_column": ("hello\nworld\n", [["hello"], ["world"]]),
}

_PY_FENCE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# The driver IMPORTS the candidate as a module (so any
# `if __name__ == "__main__":` demo block in the candidate does not run) and
# exchanges data via files (so candidate prints cannot corrupt the protocol).
_DRIVER = """
import json
import sys
sys.path.insert(0, ".")  # -I strips cwd; the candidate module lives here
import candidate_module
fixtures = json.load(open("fixtures.json", encoding="utf-8"))
results = {}
for label, text in fixtures.items():
    try:
        results[label] = candidate_module.parse_csv(text)
    except Exception as exc:
        results[label] = {"__error__": f"{type(exc).__name__}: {exc}"}
json.dump(results, open("results.json", "w", encoding="utf-8"))
"""


def extract_python(text: str) -> Optional[str]:
    """Prefer the last block that defines parse_csv; outputs commonly append
    a short usage-example block that must not shadow the implementation."""
    blocks = [b.strip() for b in _PY_FENCE.findall(text)]
    defining = [b for b in blocks if "def parse_csv" in b]
    if defining:
        return defining[-1]
    return blocks[-1] if blocks else None


def run_candidate(code: str, timeout: float = 10.0) -> tuple[Optional[dict], str]:
    """Import candidate as a module in a subprocess, run fixtures through
    parse_csv via file-based IO; returns (results, error)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "candidate_module.py").write_text(code, encoding="utf-8")
        (Path(tmp) / "driver.py").write_text(_DRIVER, encoding="utf-8")
        (Path(tmp) / "fixtures.json").write_text(
            json.dumps({label: text for label, (text, _) in FIXTURES.items()}),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "driver.py"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
        if proc.returncode != 0:
            return None, (proc.stderr or "nonzero exit").strip()[-400:]
        results_path = Path(tmp) / "results.json"
        if not results_path.exists():
            return None, "driver produced no results file"
        try:
            return json.loads(results_path.read_text(encoding="utf-8")), ""
        except json.JSONDecodeError:
            return None, "unparseable results file"


def gold_verdict(task_id: str, output_text: str) -> tuple[bool, dict]:
    assert task_id == "csv_parser", task_id
    code = extract_python(output_text)
    if code is None:
        return False, {"reason": "no python code block found in output"}
    if "def parse_csv" not in code:
        return False, {"reason": "no parse_csv function defined"}
    results, error = run_candidate(code)
    if results is None:
        return False, {"reason": f"execution failed: {error}"}
    failures = []
    for label, (_, expected) in FIXTURES.items():
        actual = results.get(label)
        if actual != expected:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}"[:300])
    if failures:
        return False, {"reason": "fixture mismatch", "failures": failures}
    return True, {"fixtures": len(FIXTURES)}


def sanity_check() -> None:
    ok, meta = gold_verdict("csv_parser", REFERENCE_OUTPUT)
    assert ok, f"reference parser failed its own fixtures: {meta}"


if __name__ == "__main__":
    sanity_check()
    print(f"csv_gold sanity checks passed ({len(FIXTURES)} fixtures)")
