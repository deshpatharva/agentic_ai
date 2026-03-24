"""
In-memory result cache keyed by SHA-256 hash of inputs.
Used to avoid redundant Claude calls for identical inputs within a session.
"""

import hashlib
from typing import Any, Optional

_cache: dict[str, Any] = {}


def _key(*parts: str) -> str:
    combined = "||".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()


def get(*parts: str) -> Optional[Any]:
    return _cache.get(_key(*parts))


def set(*parts: str, value: Any) -> None:
    _cache[_key(*parts)] = value


def clear() -> None:
    _cache.clear()
