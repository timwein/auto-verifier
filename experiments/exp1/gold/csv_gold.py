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

_DRIVER = """
import json, sys
fixtures = json.loads(sys.stdin.read())
results = {}
for label, text in fixtures.items():
    try:
        results[label] = parse_csv(text)
    except Exception as exc:
        results[label] = {"__error__": f"{type(exc).__name__}: {exc}"}
print(json.dumps(results))
"""


def extract_python(text: str) -> Optional[str]:
    blocks = _PY_FENCE.findall(text)
    return blocks[-1].strip() if blocks else None


def run_candidate(code: str, timeout: float = 10.0) -> tuple[Optional[dict], str]:
    """Run candidate code + driver in a subprocess; returns (results, error)."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "candidate.py"
        script.write_text(code + "\n" + _DRIVER, encoding="utf-8")
        payload = json.dumps({label: text for label, (text, _) in FIXTURES.items()})
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
    if proc.returncode != 0:
        return None, (proc.stderr or "nonzero exit").strip()[-400:]
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1]), ""
    except (json.JSONDecodeError, IndexError):
        return None, "unparseable driver output"


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
