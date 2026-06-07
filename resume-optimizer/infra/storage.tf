# ── Storage Account ───────────────────────────────────────────────────────────

resource "azurerm_storage_account" "main" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # Locally redundant — cheapest, fine for dev
  account_kind             = "StorageV2"
  access_tier              = "Hot"

  # Enable hierarchical namespace for ADLS Gen2 (required for Delta Lake ABFS paths)
  is_hns_enabled = true

  # All access is via AAD role assignments (MI for the app, SP for CI/CD).
  # Shared-key access is disabled so the storage account key cannot be used,
  # which removes it as an attack surface even if it were leaked.
  shared_access_key_enabled = false

  # No public blob access — AAD credential required for all reads and writes
  allow_nested_items_to_be_public = false

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }

  tags = local.tags
}

# ── Containers ────────────────────────────────────────────────────────────────

resource "azurerm_storage_container" "uploads" {
  name                  = local.uploads_container
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "outputs" {
  name                  = local.outputs_container
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "delta" {
  name                  = local.delta_container
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

# ── Service Principal → Storage Blob Data Contributor ────────────────────────
# The SP is used only by CI/CD (GitHub Actions OIDC).  The App Service uses its
# Managed Identity (azurerm_role_assignment.mi_storage_contributor in app_service.tf).

resource "azurerm_role_assignment" "sp_storage_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azuread_service_principal.app.object_id
}
