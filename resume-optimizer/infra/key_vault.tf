import {
  to = azurerm_key_vault_secret.jwt_secret
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/JWT-SECRET/ed7025d4703245c89781532ebda82bc5"
}

import {
  to = azurerm_key_vault_secret.database_url
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/DATABASE-URL/8c217b28bb254bdab9e945fd05c7cee6"
}

import {
  to = azurerm_key_vault_secret.google_ai_api_key
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/GOOGLE-AI-STUDIO-API-KEY/2c474d7c916347d1b0c520899aae5c07"
}

import {
  to = azurerm_key_vault_secret.groq_api_key
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/GROQ-API-KEY/d321d75422e14cb7902971d8df77ab5c"
}

import {
  to = azurerm_key_vault_secret.anthropic_api_key
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/ANTHROPIC-API-KEY/d11c6d07f664440d9c49c09c37235645"
}

import {
  to = azurerm_key_vault_secret.azure_storage_account_name
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/AZURE-STORAGE-ACCOUNT-NAME/b486ee24a1bc4d6391573bd6bf44b8a6"
}

import {
  to = azurerm_key_vault_secret.delta_storage_path
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/DELTA-STORAGE-PATH/e0f227dc0bb04facb50f0ef808327dae"
}

import {
  to = azurerm_key_vault_secret.adzuna_app_id
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/ADZUNA-APP-ID/08d33189f9a64f758cacaf21bc3acd80"
}

import {
  to = azurerm_key_vault_secret.adzuna_app_key
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/ADZUNA-APP-KEY/e1564ee53de14b2a9a4f2323370d5780"
}

import {
  to = azurerm_key_vault_secret.the_muse_api_key
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/THE-MUSE-API-KEY/4529b50de6d7406386ef2a8ec0eef8f1"
}

import {
  to = azurerm_key_vault_secret.apify_token
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/APIFY-TOKEN/de73e17f7b924fff96046444b0a2ac0f"
}

import {
  to = azurerm_key_vault_secret.stripe_secret_key
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/STRIPE-SECRET-KEY/b6ee9645bead4234b9cf1d55293485da"
}

import {
  to = azurerm_key_vault_secret.sp_tenant_id
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/AZURE-TENANT-ID/0dbb407bc02342d1b77aa9832f2e6871"
}

import {
  to = azurerm_key_vault_secret.sp_client_id
  id = "https://resumeaikvdevnp.vault.azure.net/secrets/AZURE-CLIENT-ID/0118efad42bb4546b3579e499d5d5e55"
}

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
  principal_id         = var.sp_object_id
}

# ── Secrets ───────────────────────────────────────────────────────────────────
# Every secret depends on time_sleep.wait_for_kv_rbac, not directly on the role
# assignment, so first-apply 403s are avoided.
#
# Secrets NOT stored here (removed from KV):
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
  value        = var.client_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_kv_rbac]
  tags         = local.tags
}
