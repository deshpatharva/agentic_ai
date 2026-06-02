# ── Key Vault ─────────────────────────────────────────────────────────────────

resource "azurerm_key_vault" "main" {
  name                       = local.key_vault_name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # false = easier teardown in dev; set true for prod

  # Azure RBAC for secrets — no legacy access policies
  enable_rbac_authorization = true

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

resource "azurerm_role_assignment" "sp_kv_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azuread_service_principal.app.object_id
}

# ── Secrets ───────────────────────────────────────────────────────────────────
# Every secret depends on time_sleep.wait_for_kv_rbac, not directly on the role
# assignment, so first-apply 403s are avoided.

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
  value = "postgresql+asyncpg://${var.postgres_admin_login}:${urlencode(random_password.postgres_password.result)}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${var.postgres_db_name}?ssl=require"
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "google_ai_api_key" {
  name         = "GOOGLE-AI-STUDIO-API-KEY"
  value        = var.google_ai_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "groq_api_key" {
  name         = "GROQ-API-KEY"
  value        = var.groq_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "anthropic_api_key" {
  name         = "ANTHROPIC-API-KEY"
  value        = var.anthropic_api_key
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

resource "azurerm_key_vault_secret" "azure_storage_account_key" {
  name         = "AZURE-STORAGE-ACCOUNT-KEY"
  value        = azurerm_storage_account.main.primary_access_key
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

resource "azurerm_key_vault_secret" "adzuna_app_id" {
  name         = "ADZUNA-APP-ID"
  value        = var.adzuna_app_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "adzuna_app_key" {
  name         = "ADZUNA-APP-KEY"
  value        = var.adzuna_app_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "the_muse_api_key" {
  name         = "THE-MUSE-API-KEY"
  value        = var.the_muse_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "apify_token" {
  name         = "APIFY-TOKEN"
  value        = var.apify_token
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "stripe_secret_key" {
  name         = "STRIPE-SECRET-KEY"
  value        = var.stripe_secret_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "sp_tenant_id" {
  name         = "AZURE-TENANT-ID"
  value        = data.azurerm_client_config.current.tenant_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "sp_client_id" {
  name         = "AZURE-CLIENT-ID"
  value        = azuread_application.app.client_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "sp_client_secret" {
  name         = "AZURE-CLIENT-SECRET"
  value        = azuread_service_principal_password.app.value
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}
