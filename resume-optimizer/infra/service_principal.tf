# ── Azure AD App Registration (UPDATED TO DATA LOOKUPS) ───────────────────────

data "azuread_client_config" "current" {}

# 1. Changed to data block and supplied your exact Client ID from the portal
data "azuread_application" "app" {
  client_id = var.client_id
}

# 2. Changed to data block because your pipeline identity's service principal already exists
data "azuread_service_principal" "app" {
  client_id = data.azuread_application.app.client_id
}

# ── OIDC Federated Identity Credentials (no stored secret) ───────────────────
# GitHub Actions authenticates to Azure via OIDC — no client_secret is created,
# stored, or rotated.  The SP is used only by CI/CD pipelines.

resource "azuread_application_federated_identity_credential" "github_main" {
  application_id = data.azuread_application.app.id # Updated reference to use data block
  display_name   = "github-main"
  description    = "GitHub Actions OIDC — deshpatharva/agentic_ai main branch"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:deshpatharva/agentic_ai:ref:refs/heads/main"
}

resource "azuread_application_federated_identity_credential" "github_env_production" {
  application_id = data.azuread_application.app.id # Updated reference to use data block
  display_name   = "github-env-production"
  description    = "GitHub Actions OIDC — deshpatharva/agentic_ai production environment"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:deshpatharva/agentic_ai:environment:production"
}

# ── Terraform caller → Key Vault Administrator ────────────────────────────────
# Grants this apply run write access to Key Vault secrets.

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "terraform_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}
