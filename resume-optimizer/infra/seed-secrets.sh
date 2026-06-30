#!/usr/bin/env bash
#
# Seed externally-sourced secrets into Key Vault, out-of-band from Terraform.
#
# These secrets are intentionally NOT managed by Terraform (see key_vault.tf):
# rotating one is just a re-run of `az keyvault secret set` (or this script) —
# no `terraform apply`, no value in tfstate. App Service references them by name
# (versionless) so the new version is picked up automatically.
#
# Usage:
#   export GOOGLE_AI_API_KEY=...  GROQ_API_KEY=...  DEEPSEEK_API_KEY=...
#   export ANTHROPIC_API_KEY=...  BOOTSTRAP_SECRET=...   # required
#   export STRIPE_SECRET_KEY=...  ADZUNA_APP_ID=... ...  # optional
#   ./seed-secrets.sh <key-vault-name>
#
# The caller needs the "Key Vault Secrets Officer" (or Administrator) role on the
# vault. The Terraform deploy principal already has Administrator.
set -euo pipefail

VAULT="${1:?Usage: ./seed-secrets.sh <key-vault-name>}"

# Generate a BOOTSTRAP-SECRET if the operator didn't supply one.
if [[ -z "${BOOTSTRAP_SECRET:-}" ]]; then
  BOOTSTRAP_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "note: generated a BOOTSTRAP-SECRET (save it if you need admin bootstrap)."
fi

# secret-name  →  env-var holding the value     (required?)
set_secret() {
  local name="$1" value="$2" required="$3"
  if [[ -z "$value" ]]; then
    if [[ "$required" == "required" ]]; then
      echo "ERROR: $name is required but its value is empty." >&2; exit 1
    fi
    echo "skip   $name (optional, not provided)"; return 0
  fi
  az keyvault secret set --vault-name "$VAULT" --name "$name" --value "$value" --output none
  echo "set    $name"
}

set_secret "GOOGLE-AI-STUDIO-API-KEY" "${GOOGLE_AI_API_KEY:-}" required
set_secret "GROQ-API-KEY"             "${GROQ_API_KEY:-}"      required
set_secret "DEEPSEEK-API-KEY"         "${DEEPSEEK_API_KEY:-}"  required
set_secret "ANTHROPIC-API-KEY"        "${ANTHROPIC_API_KEY:-}" required
set_secret "BOOTSTRAP-SECRET"         "${BOOTSTRAP_SECRET}"    required
set_secret "STRIPE-SECRET-KEY"        "${STRIPE_SECRET_KEY:-}" optional
set_secret "ADZUNA-APP-ID"            "${ADZUNA_APP_ID:-}"     optional
set_secret "ADZUNA-APP-KEY"           "${ADZUNA_APP_KEY:-}"    optional
set_secret "THE-MUSE-API-KEY"         "${THE_MUSE_API_KEY:-}"  optional
set_secret "APIFY-TOKEN"              "${APIFY_TOKEN:-}"       optional

echo "done. App Service picks up new versions automatically (versionless KV refs)."
