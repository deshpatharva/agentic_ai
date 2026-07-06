"""Regression: the shared spaCy pipeline must be called through a serializing
wrapper. fabrication_guard/extract_claims now run inside asyncio.to_thread from
multiple concurrent pipelines (agent_loop, debate_loop), and a spaCy Language
object is not safe for concurrent __call__.
"""

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_nlp.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")


def test_nlp_process_serializes_concurrent_calls(monkeypatch):
    from agents import fact_extractor as fe

    counter_lock = threading.Lock()
    active = {"n": 0}
    peak = {"n": 0}

    def fake_nlp(text):
        # Detect overlapping execution: bump active on entry, record the peak.
        with counter_lock:
            active["n"] += 1
            peak["n"] = max(peak["n"], active["n"])
        time.sleep(0.01)          # widen the window for overlap to show
        with counter_lock:
            active["n"] -= 1
        return text

    monkeypatch.setattr(fe, "nlp", fake_nlp)

    threads = [threading.Thread(target=lambda: fe.nlp_process("x")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # If nlp_process locks, at most one fake_nlp body runs at a time.
    assert peak["n"] == 1, f"concurrent nlp access observed (peak={peak['n']})"
