from slowapi import Limiter


def _strip_port(entry: str) -> str:
    """Normalize an XFF entry to a bare IP.

    Azure App Service's front end appends the client as 'IP:port' — the ephemeral
    port would otherwise mint a fresh rate-limit bucket per TCP connection and
    silently disable every per-IP limit. Handles bracketed IPv6 ('[2001:db8::1]:8080')
    and 'IPv4:port'; a bare IPv6 (2+ colons, no brackets) or bare IPv4 (no colon)
    passes through untouched.
    """
    if entry.startswith("["):
        return entry[1:].split("]", 1)[0]
    if entry.count(":") == 1:
        return entry.split(":", 1)[0]
    return entry


def _client_ip(request) -> str:
    """Rate-limit key: the real client IP, resistant to X-Forwarded-For spoofing.

    On Azure App Service the platform front-end appends the true client IP as the
    LAST entry of X-Forwarded-For (standard XFF: each proxy appends the address it
    received the request from). Entries a client prepends to forge a fresh bucket
    sit to the left and are ignored. Falls back to the socket peer when the header
    is absent (local/dev). This must NOT trust the leftmost entry — that is exactly
    the value an attacker controls.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return _strip_port(parts[-1])
    client = getattr(request, "client", None)
    if client and client.host:
        return client.host
    return "127.0.0.1"


limiter = Limiter(key_func=_client_ip)
