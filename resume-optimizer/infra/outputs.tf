# ── Identity ──────────────────────────────────────────────────────────────────

output "tenant_id" {
  description = "Azure AD Tenant ID"
  value       = data.azurerm_client_config.current.tenant_id
}

output "service_principal_client_id" {
  description = "Service Principal Client ID — put this in your local .env as AZURE_CLIENT_ID"
  value       = azuread_application.app.client_id
}

output "service_principal_client_secret" {
  description = "Service Principal Client Secret — put this in your local .env as AZURE_CLIENT_SECRET"
  value       = azuread_service_principal_password.app.value
  sensitive   = true
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

output "storage_account_key" {
  description = "Storage account primary access key"
  value       = azurerm_storage_account.main.primary_access_key
  sensitive   = true
}

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
  description = "Deploy token for GitHub Actions / CI — add as AZURE_STATIC_WEB_APPS_API_TOKEN secret"
  value       = azurerm_static_web_app.frontend.api_key
  sensitive   = true
}

# ── Local .env snippet ────────────────────────────────────────────────────────

output "local_env_snippet" {
  description = "Copy these 4 lines into resume-optimizer/.env for local development"
  sensitive   = true
  value       = <<-EOT
    AZURE_TENANT_ID=${data.azurerm_client_config.current.tenant_id}
    AZURE_CLIENT_ID=${azuread_application.app.client_id}
    AZURE_CLIENT_SECRET=${azuread_service_principal_password.app.value}
    KEY_VAULT_URL=${azurerm_key_vault.main.vault_uri}
  EOT
}
