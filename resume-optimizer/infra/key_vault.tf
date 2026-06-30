# ── Key Vault ─────────────────────────────────────────────────────────────────

resource "azurerm_key_vault" "main" {
  name                       = local.key_vault_name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = true

  # Azure RBAC for secrets — no legacy access policies
  rbac_authorization_enabled = true

  tags = local.tags
}

# ── Terraform caller → Key Vault Administrator ────────────────────────────────
# Required so this run can write secrets.  Defined in service_principal.tf.

# ── RBAC propagation guard ────────────────────────────────────────────────────
# Azure RBAC assignments can take up to ~60 s to propagate across the control
# plane.  Without this sleep the first apply races and gets 403s on secret writes.

resource "time_sleep" "wait_for_kv_rbac" {
  depends_on      = [azurerm_role_assignment.terraform_kv_admin]
  create_duration = "60s"
}

# ── Service Principal → Key Vault Secrets User ────────────────────────────────
# The SP is used only by CI/CD (GitHub Actions OIDC); it reads secrets for
# deployment pipelines.  The App Service uses its Managed Identity instead.

resource "azurerm_role_assignment" "sp_kv_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ── Secrets ───────────────────────────────────────────────────────────────────
# Terraform manages ONLY secrets it derives from infra it owns (JWT, DATABASE-URL,
# storage/SP identifiers). Externally-sourced secrets (all API keys, Stripe,
# BOOTSTRAP) are NO LONGER created here — they are seeded out-of-band via
# `az keyvault secret set` (see seed-secrets.sh) so rotation never needs a
# terraform apply. App Service references them by name (versionless) in app_service.tf.
#
# Every TF-managed secret depends on time_sleep.wait_for_kv_rbac, not directly on
# the role assignment, so first-apply 403s are avoided.
#
# Secrets NOT stored here:
#   AZURE-CLIENT-SECRET      — SP has no password; CI/CD uses OIDC
#   AZURE-STORAGE-ACCOUNT-KEY — shared key access disabled on the storage account

resource "azurerm_key_vault_secret" "jwt_secret" {
  name         = "JWT-SECRET"
  value        = random_password.jwt_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "database_url" {
  name = "DATABASE-URL"
  # urlencode() percent-encodes every char that is not unreserved in a URL
  # (letters, digits, -, _, ., ~) — belt-and-suspenders on top of the
  # URL-safe override_special set in random_password.postgres_password.
  value        = "postgresql+asyncpg://${var.postgres_admin_login}:${urlencode(random_password.postgres_password.result)}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${var.postgres_db_name}?ssl=require"
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "azure_storage_account_name" {
  name         = "AZURE-STORAGE-ACCOUNT-NAME"
  value        = azurerm_storage_account.main.name
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "delta_storage_path" {
  name         = "DELTA-STORAGE-PATH"
  value        = local.delta_storage_path
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

# SP identity values — non-sensitive GUIDs, stored for config.py local-dev parity

resource "azurerm_key_vault_secret" "sp_tenant_id" {
  name         = "AZURE-TENANT-ID"
  value        = data.azurerm_client_config.current.tenant_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "sp_client_id" {
  name         = "AZURE-CLIENT-ID"
  value        = data.azurerm_client_config.current.client_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}
