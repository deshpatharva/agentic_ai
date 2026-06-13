"""Stage B P3 (R3): the result cache must be bounded."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import cache


def setup_function():
    cache.clear()


def test_cache_get_set_roundtrip():
    cache.set("jd", "text-a", value={"k": 1})
    assert cache.get("jd", "text-a") == {"k": 1}
    assert cache.get("jd", "text-b") is None


def test_cache_evicts_least_recently_used():
    for i in range(cache.MAX_ENTRIES + 10):
        cache.set("jd", f"text-{i}", value=i)
    # the first 10 should have been evicted; the most recent survive
    assert cache.get("jd", "text-0") is None
    assert cache.get("jd", f"text-{cache.MAX_ENTRIES + 9}") == cache.MAX_ENTRIES + 9
    assert len(cache._cache) == cache.MAX_ENTRIES


def test_cache_recent_use_protects_from_eviction():
    cache.set("jd", "keep-me", value="kept")
    for i in range(cache.MAX_ENTRIES - 1):
        cache.set("jd", f"filler-{i}", value=i)
    cache.get("jd", "keep-me")          # touch → most recently used
    cache.set("jd", "overflow", value=1)  # evicts ONE entry — not keep-me
    assert cache.get("jd", "keep-me") == "kept"
