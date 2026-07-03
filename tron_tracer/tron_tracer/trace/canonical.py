"""Canonical, deterministic JSON serialization (blueprint Sec 1, Sec 5.5).

Sorted keys, no whitespace variance, integers serialize as JSON integers
(never floats -- Python's json module already does this correctly for
`int`, including arbitrary precision). Used for the trace output
document, audit log hashing, and any other artifact whose hash must be
reproducible run-to-run.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json_dumps(obj).encode("utf-8")).hexdigest()
