# ── Azure AD App Registration ─────────────────────────────────────────────────

data "azuread_client_config" "current" {}

resource "azuread_application" "app" {
  display_name = local.sp_app_name
  owners       = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "app" {
  client_id                    = azuread_application.app.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
}

# ── OIDC Federated Identity Credentials (no stored secret) ───────────────────
# GitHub Actions authenticates to Azure via OIDC — no client_secret is created,
# stored, or rotated.  The SP is used only by CI/CD pipelines.
#
# GitHub Actions workflow must set:
#   permissions:
#     id-token: write
#     contents: read
#
# And use the azure/login action with:
#   client-id:       ${{ secrets.AZURE_CLIENT_ID }}    (non-sensitive GUID)
#   tenant-id:       ${{ secrets.AZURE_TENANT_ID }}    (non-sensitive GUID)
#   subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

resource "azuread_application_federated_identity_credential" "github_main" {
  application_id = azuread_application.app.id
  display_name   = "github-main"
  description    = "GitHub Actions OIDC — deshpatharva/agentic_ai main branch"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:deshpatharva/agentic_ai:ref:refs/heads/main"
}

resource "azuread_application_federated_identity_credential" "github_env_production" {
  application_id = azuread_application.app.id
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
