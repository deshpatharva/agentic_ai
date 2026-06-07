# ── Terraform caller → Key Vault Administrator ────────────────────────────────
# Grants this apply run write access to Key Vault secrets.

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "terraform_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}
