"""The rate-limit key must be resistant to X-Forwarded-For spoofing.

Azure App Service's front-end appends the true client IP as the LAST XFF entry;
a client can only prepend forged entries to the left. Keying on the rightmost
entry means a client rotating a spoofed value can't mint a fresh bucket per
request and bypass per-IP limits.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_req(xff=None, client_host=None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    client = types.SimpleNamespace(host=client_host) if client_host else None
    return types.SimpleNamespace(headers=headers, client=client)


def test_uses_rightmost_xff_entry():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="6.6.6.6, 203.0.113.9")) == "203.0.113.9"


def test_single_entry():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="203.0.113.9")) == "203.0.113.9"


def test_spoofed_rotation_maps_to_same_real_client():
    from limiter import _client_ip
    a = _client_ip(_make_req(xff="1.1.1.1, 203.0.113.9"))
    b = _client_ip(_make_req(xff="2.2.2.2, 203.0.113.9"))
    assert a == b == "203.0.113.9"


def test_falls_back_to_socket_peer_without_xff():
    from limiter import _client_ip
    assert _client_ip(_make_req(client_host="9.9.9.9")) == "9.9.9.9"


def test_default_when_nothing_available():
    from limiter import _client_ip
    assert _client_ip(_make_req()) == "127.0.0.1"


def test_ignores_trailing_empty_entries():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="203.0.113.9, ")) == "203.0.113.9"


def test_strips_port_azure_format():
    # Azure App Service's front end appends the client as 'IP:port'.
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="203.0.113.9:54321")) == "203.0.113.9"


def test_strips_port_multi_entry():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="6.6.6.6, 203.0.113.9:49152")) == "203.0.113.9"


def test_port_varies_but_bucket_is_stable():
    from limiter import _client_ip
    a = _client_ip(_make_req(xff="203.0.113.9:54321"))
    b = _client_ip(_make_req(xff="203.0.113.9:54988"))
    assert a == b == "203.0.113.9"


def test_bracketed_ipv6_with_port():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="[2001:db8::1]:8080")) == "2001:db8::1"


def test_bare_ipv6_untouched():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="2001:db8::1")) == "2001:db8::1"
