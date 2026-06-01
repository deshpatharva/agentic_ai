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

# Rotate by changing the rotation_days or end_date values
resource "azuread_service_principal_password" "app" {
  service_principal_id = azuread_service_principal.app.id
  display_name         = "terraform-managed"

  rotate_when_changed = {
    rotation = "2026-01-01" # Update this date to force password rotation
  }
}

# ── Terraform caller gets Key Vault admin (so it can write secrets) ───────────

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "terraform_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}
