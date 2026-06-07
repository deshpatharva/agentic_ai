# ── OIDC Federated Identity Credentials ──────────────────────────────────────

resource "azuread_application_federated_identity_credential" "github_main" {
  # Fix: Prepend the literal path segment before your variable string
  application_id = "/applications/${var.app_object_id}"

  display_name = "github-main"
  description  = "GitHub Actions OIDC — deshpatharva/agentic_ai main branch"
  audiences    = ["api://AzureADTokenExchange"]
  issuer       = "https://token.actions.githubusercontent.com"
  subject      = "repo:deshpatharva/agentic_ai:ref:refs/heads/main"
}

resource "azuread_application_federated_identity_credential" "github_env_production" {
  # Fix: Prepend the literal path segment before your variable string
  application_id = "/applications/${var.app_object_id}"

  display_name = "github-env-production"
  description  = "GitHub Actions OIDC — deshpatharva/agentic_ai production environment"
  audiences    = ["api://AzureADTokenExchange"]
  issuer       = "https://token.actions.githubusercontent.com"
  subject      = "repo:deshpatharva/agentic_ai:environment:production"
}

# ── Terraform caller → Key Vault Administrator ────────────────────────────────
# Grants this apply run write access to Key Vault secrets.

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "terraform_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}
