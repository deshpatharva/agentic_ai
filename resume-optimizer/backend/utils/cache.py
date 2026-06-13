"""
In-memory LRU result cache keyed by SHA-256 hash of inputs.
Avoids redundant LLM calls for identical inputs (currently: JD analysis).

Bounded: at most MAX_ENTRIES live at once — least-recently-used entries are
evicted, so a long-lived server can't leak memory through unique JD texts.
"""

import hashlib
import threading
from collections import OrderedDict
from typing import Any, Optional

MAX_ENTRIES = 256

_cache: "OrderedDict[str, Any]" = OrderedDict()
_lock = threading.Lock()


def _key(*parts: str) -> str:
    combined = "||".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()


def get(*parts: str) -> Optional[Any]:
    k = _key(*parts)
    with _lock:
        if k not in _cache:
            return None
        _cache.move_to_end(k)  # mark as recently used
        return _cache[k]


def set(*parts: str, value: Any) -> None:
    k = _key(*parts)
    with _lock:
        _cache[k] = value
        _cache.move_to_end(k)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)  # evict least-recently-used


def clear() -> None:
    with _lock:
        _cache.clear()
