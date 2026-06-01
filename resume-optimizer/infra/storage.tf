# ── Storage Account ───────────────────────────────────────────────────────────

resource "azurerm_storage_account" "main" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"            # Locally redundant — cheapest, fine for dev
  account_kind             = "StorageV2"
  access_tier              = "Hot"

  # Enable hierarchical namespace for ADLS Gen2 (required for Delta Lake ABFS paths)
  is_hns_enabled = true

  # Disable public blob access — SP credential required for all access
  allow_nested_items_to_be_public = false

  blob_properties {
    # Soft delete for blobs — 7 day recovery window
    delete_retention_policy {
      days = 7
    }
  }

  tags = local.tags
}

# ── Containers ────────────────────────────────────────────────────────────────

resource "azurerm_storage_container" "uploads" {
  name                  = local.uploads_container
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "outputs" {
  name                  = local.outputs_container
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "delta" {
  name                  = local.delta_container
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# ── Service Principal → Storage Blob Data Contributor ────────────────────────
# Grants read + write + delete on blobs — required for uploads, outputs, and Delta Lake

resource "azurerm_role_assignment" "sp_storage_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.app.object_id
}
