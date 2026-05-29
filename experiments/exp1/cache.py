#!/usr/bin/env python3
from __future__ import annotations
"""
Content-hash cache for Exp-1 (stdlib only).

Gold verdicts and gate scores are deterministic-ish; key by a hash of their inputs
so debug re-runs are free. Local to exp1 — not a shared repo helper.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

_CACHE_DIR = Path(__file__).resolve().parent / "results" / ".cache"


def _key(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class Cache:
    def __init__(self, namespace: str, enabled: bool = True):
        self.enabled = enabled
        self.dir = _CACHE_DIR / namespace
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def get_or_compute(self, key_parts: tuple, compute: Callable[[], Any]) -> Any:
        if not self.enabled:
            return compute()
        path = self.dir / f"{_key(*key_parts)}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())["value"]
            except Exception:
                pass
        value = compute()
        try:
            path.write_text(json.dumps({"key": list(map(str, key_parts)), "value": value}))
        except Exception:
            pass
        return value
