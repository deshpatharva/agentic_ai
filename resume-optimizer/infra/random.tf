# ── Globally-unique suffix ────────────────────────────────────────────────────
# Appended to Key Vault and Storage Account names, which must be globally unique.
# Stable within a state file; different workspaces get different suffixes.

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

# ── JWT secret ────────────────────────────────────────────────────────────────

resource "random_password" "jwt_secret" {
  length  = 64
  special = false # alphanumeric only — safe in all env-var consumers
}

# ── PostgreSQL password ───────────────────────────────────────────────────────
# override_special is restricted to chars that are safe in a URL userinfo
# segment without percent-encoding (RFC 3986 §3.2.1).
# The DATABASE-URL secret additionally wraps the password in urlencode() as a
# belt-and-suspenders guard.

resource "random_password" "postgres_password" {
  length           = 32
  special          = true
  override_special = "!-_="
}
