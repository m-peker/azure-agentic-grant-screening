"""Content-addressed JSON cache for paid or quota-limited service calls.

Key = namespace + SHA-256 of the inputs. The same PDF analysed twice costs one
call. Changing the input (or the model / prompt version inside `parts`) changes
the key, so stale results are never reused by accident.

Cache files live under .cache/ (git-ignored).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

CACHE_ROOT = Path(__file__).resolve().parents[2] / ".cache"


def digest(*parts: bytes | str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def trial_salt() -> str:
    """Evaluation trials: a different salt gives model calls fresh cache keys (and fresh samples),
    while deterministic services (Layout, Prompt Shields, PII, embeddings) stay cached."""
    import os

    return os.environ.get("GRANT_TRIAL", "")


def cached_json(namespace: str, key: str, compute: Callable[[], Any]) -> Any:
    path = CACHE_ROOT / namespace / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value
