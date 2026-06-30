# Migration: move externally-sourced secrets out of Terraform

We stopped managing externally-sourced secrets (all API keys, Stripe, BOOTSTRAP)
in Terraform. They are now seeded out-of-band so rotation never needs a
`terraform apply`. Terraform still manages secrets it derives from its own infra
(`JWT-SECRET`, `DATABASE-URL`, storage/SP identifiers).

## ⚠️ One-time migration on existing environments

Existing state still tracks the 10 removed `azurerm_key_vault_secret` resources.
Running `terraform apply` as-is would **destroy those secrets in Key Vault**
(they'd soft-delete; purge protection keeps them recoverable for 7 days — but the
app would break in the meantime).

**Detach them from state first — this keeps the live KV secrets untouched:**

```bash
cd resume-optimizer/infra
for r in google_ai_api_key groq_api_key deepseek_api_key anthropic_api_key \
         adzuna_app_id adzuna_app_key the_muse_api_key apify_token \
         stripe_secret_key bootstrap_secret; do
  terraform state rm "azurerm_key_vault_secret.$r" || true
done

terraform plan   # should now show NO destroy of those secrets
terraform apply  # updates App Service settings to by-name (versionless) refs
```

## Fresh environments

Terraform creates the vault + app, but **not** the externally-sourced secrets.
Seed them after the vault exists, then restart the app so KV references resolve:

```bash
export GOOGLE_AI_API_KEY=... GROQ_API_KEY=... DEEPSEEK_API_KEY=... \
       ANTHROPIC_API_KEY=... BOOTSTRAP_SECRET=...        # required
export STRIPE_SECRET_KEY=... ADZUNA_APP_ID=...           # optional
./seed-secrets.sh "$(terraform output -raw key_vault_name)"
az webapp restart --name <app> --resource-group <rg>
```

## Rotating a secret (the whole point)

```bash
az keyvault secret set --vault-name <vault> --name DEEPSEEK-API-KEY --value <new>
```

App Service references are versionless, so it picks up the new version
automatically (within its secret-resolution cache window) — no Terraform, no redeploy.

## GitHub Actions

The `TF_VAR_*` secret env vars were removed from `terraform.yml`. The
`TF_VAR_GOOGLE_AI_API_KEY` / `TF_VAR_GROQ_API_KEY` / `TF_VAR_ANTHROPIC_API_KEY` /
`TF_VAR_DEEPSEEK_API_KEY` / `TF_VAR_BOOTSTRAP_SECRET` repo secrets are no longer
used by Terraform and can be deleted once the migration is applied.
