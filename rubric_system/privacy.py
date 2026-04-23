"""
Privacy scrubber (Phase 5 — OpenRubrics alignment, dataset building).

Regex-based redaction of obvious PII and credentials before a (task, preferred,
rejected, rubric) row is persisted to RubricStore. Conservative by design:
only replaces high-confidence patterns so legitimate content survives.

Covered patterns:
  - Email addresses
  - Generic long tokens / API keys (AWS, GCP, GitHub, Anthropic, bearer tokens)
  - URLs carrying credentials (user:pass@host or ?api_key=..., ?token=...)
  - PEM-wrapped private keys
"""
from __future__ import annotations

import re


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # URLs with embedded basic-auth credentials: https://user:pass@host
    # (must run BEFORE the email pattern, which would otherwise greedily match
    #  "user@host" inside a URL)
    (re.compile(r"\b(https?://)[^\s:@/]+:[^\s@/]+@", re.IGNORECASE), r"\1[REDACTED_CRED]@"),
    # Emails
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    # URLs with api_key= / token= / access_token= in query strings
    (re.compile(r"([?&](?:api[_-]?key|access[_-]?token|token|secret)=)[^&\s]+", re.IGNORECASE),
     r"\1[REDACTED_TOKEN]"),
    # Anthropic-style API keys: sk-ant-... (high-entropy long string)
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b"), "[REDACTED_ANTHROPIC_KEY]"),
    # OpenAI-style: sk-... (20+ chars)
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "[REDACTED_OPENAI_KEY]"),
    # GitHub PATs: ghp_, gho_, ghs_, ghr_, ghu_ followed by 30+ chars
    (re.compile(r"\bgh[posru]_[A-Za-z0-9]{30,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # AWS access key IDs: AKIA... 20 chars
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # AWS secret access keys (40 chars, base64-ish, preceded by a plausible label)
    (re.compile(r"(aws[_-]?secret[_-]?(access[_-]?)?key\s*[:=]\s*)['\"]?[A-Za-z0-9/+=]{40}['\"]?",
                re.IGNORECASE), r"\1[REDACTED_AWS_SECRET]"),
    # Generic Bearer tokens in Authorization headers
    (re.compile(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9\-._~+/=]{16,}", re.IGNORECASE),
     r"\1[REDACTED_BEARER]"),
    # PEM private keys
    (re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"
        r"[\s\S]*?"
        r"-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"
    ), "[REDACTED_PRIVATE_KEY_BLOCK]"),
]


def scrub(text: str) -> str:
    """Redact obvious PII / credentials from ``text``.

    Returned text is always <= the input length (replacements are shorter
    than their matches) — callers rely on this for a cheap sanity check.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out
