"""SSRF guard: resolve+validate must reject private/loopback/link-local/CGNAT
address space, and return the validated IP so the fetch can pin to it (closing
the DNS-rebinding TOCTOU where the guard's lookup and httpx's differ).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_ssrf.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


@pytest.mark.parametrize("bad_url", [
    "http://127.0.0.1/jobs",        # loopback
    "http://169.254.169.254/latest",  # cloud metadata (link-local)
    "http://10.0.0.5/",             # private
    "http://192.168.1.1/",          # private
    "http://100.64.1.1/",           # CGNAT (RFC 6598) — the newly-covered range
    "http://[::1]/",                # IPv6 loopback
    "http://0.0.0.0/",              # unspecified
])
def test_blocks_non_public_addresses(bad_url):
    from jd.router import _resolve_public_ip
    with pytest.raises(ValueError):
        _resolve_public_ip(bad_url)


@pytest.mark.parametrize("bad_url", [
    "ftp://example.com/x",
    "file:///etc/passwd",
    "gopher://example.com/",
])
def test_rejects_non_http_schemes(bad_url):
    from jd.router import _resolve_public_ip
    with pytest.raises(ValueError):
        _resolve_public_ip(bad_url)


def test_allows_public_ip_and_returns_pin_target():
    from jd.router import _resolve_public_ip
    ip, host, port = _resolve_public_ip("http://8.8.8.8/jobs?x=1")
    assert ip == "8.8.8.8"
    assert host == "8.8.8.8"
    assert port == 80


def test_https_default_port():
    from jd.router import _resolve_public_ip
    ip, host, port = _resolve_public_ip("https://8.8.4.4/")
    assert port == 443
