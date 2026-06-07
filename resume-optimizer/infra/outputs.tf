# ── Identity ──────────────────────────────────────────────────────────────────

output "tenant_id" {
  description = "Azure AD Tenant ID"
  value       = data.azurerm_client_config.current.tenant_id
}

output "service_principal_client_id" {
  description = "Service Principal Client ID (non-secret GUID) — add as AZURE_CLIENT_ID in GitHub Actions secrets"
  value       = data.azuread_application.app.client_id
}

# ── Key Vault ─────────────────────────────────────────────────────────────────

output "key_vault_url" {
  description = "Key Vault URI — put this in your local .env as KEY_VAULT_URL"
  value       = azurerm_key_vault.main.vault_uri
}

output "key_vault_name" {
  description = "Key Vault resource name"
  value       = azurerm_key_vault.main.name
}

# ── Storage ───────────────────────────────────────────────────────────────────

output "storage_account_name" {
  description = "Storage account name"
  value       = azurerm_storage_account.main.name
}

# Note: storage_account_key is intentionally omitted — shared key access is
# disabled on the storage account.  All access is via AAD role assignments.

# ── PostgreSQL ────────────────────────────────────────────────────────────────

output "postgres_fqdn" {
  description = "PostgreSQL server fully-qualified domain name"
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_admin_login" {
  description = "PostgreSQL admin username"
  value       = var.postgres_admin_login
}

# ── App URLs ──────────────────────────────────────────────────────────────────

output "backend_url" {
  description = "FastAPI backend URL"
  value       = "https://${azurerm_linux_web_app.backend.default_hostname}"
}

output "frontend_url" {
  description = "React frontend URL (Static Web Apps)"
  value       = "https://${azurerm_static_web_app.frontend.default_host_name}"
}

output "static_web_app_deployment_token" {
  description = "Deploy token for GitHub Actions — add as AZURE_STATIC_WEB_APPS_API_TOKEN secret"
  value       = azurerm_static_web_app.frontend.api_key
  sensitive   = true
}

# ── Managed Identity ──────────────────────────────────────────────────────────

output "app_service_mi_principal_id" {
  description = "App Service Managed Identity principal ID (for reference / auditing)"
  value       = azurerm_linux_web_app.backend.identity[0].principal_id
}

# ── Remote state (backend.tf) ─────────────────────────────────────────────────

output "tfstate_storage_account_name" {
  description = "State storage account name — copy this into backend.tf after step-1 apply"
  value       = azurerm_storage_account.tfstate.name
}

output "tfstate_resource_group_name" {
  description = "Resource group containing the state storage account — copy into backend.tf"
  value       = azurerm_resource_group.main.name
}

# ── Local .env snippet ────────────────────────────────────────────────────────
# No client secret — local dev authenticates via `az login` (DefaultAzureCredential
# picks up the CLI session).  AZURE_CLIENT_ID and AZURE_TENANT_ID are non-secret
# GUIDs that config.py needs to resolve the correct identity.

output "local_env_snippet" {
  description = "Copy these 3 lines into resume-optimizer/.env for local development"
  value       = <<-EOT
    AZURE_TENANT_ID=${data.azurerm_client_config.current.tenant_id}
    AZURE_CLIENT_ID=${data.azuread_application.app.client_id}
    KEY_VAULT_URL=${azurerm_key_vault.main.vault_uri}
  EOT
}
