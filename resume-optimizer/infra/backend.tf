# ── Remote State Storage Account ─────────────────────────────────────────────
# A dedicated storage account for Terraform state.  Kept separate from the app
# storage account so destroying/recreating the app stack never touches state.
#
# IMPORTANT — two-step bootstrap:
#
#   Step 1: Apply only these three resources with local state:
#     terraform apply \
#       -target=azurerm_storage_account.tfstate \
#       -target=azurerm_storage_container.tfstate \
#       -target=azurerm_role_assignment.terraform_tfstate
#
#   Step 2: Uncomment the backend block below, then migrate:
#     terraform init -migrate-state
#     (Terraform will prompt to copy local state into the new backend.)
#
#   After migration: local terraform.tfstate can be deleted.

resource "azurerm_storage_account" "tfstate" {
  # Standard StorageV2 WITHOUT hierarchical namespace — ADLS Gen2 breaks
  # Terraform's state locking (lease operations require flat blob semantics).
  name                     = local.tfstate_storage_account_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  is_hns_enabled = false # Must be false for Terraform state locking

  # All access via AAD — use_azuread_auth = true in the backend block below
  shared_access_key_enabled = false

  allow_nested_items_to_be_public = false

  blob_properties {
    delete_retention_policy {
      days = 30 # Longer retention for state blobs
    }
    versioning_enabled = true # Enables state file history / rollback
  }

  tags = local.tags
}

resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.tfstate.id
  container_access_type = "private"
}

# Grant the Terraform operator (az login user) blob data access on the state
# account so state reads/writes work without shared keys.
resource "azurerm_role_assignment" "terraform_tfstate" {
  scope                = azurerm_storage_account.tfstate.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ── Backend Configuration ─────────────────────────────────────────────────────
# Uncomment after Step 1 apply and run: terraform init -migrate-state
#
# Fill in storage_account_name from:
#   terraform output tfstate_storage_account_name
#
# Fill in resource_group_name from:
#   terraform output tfstate_resource_group_name

terraform {
 backend "azurerm" {
   resource_group_name  = "resumeai-rg-dev"    # from output above
   storage_account_name = "resumeaitfstdevnp"  # fixed name — no random suffix
   container_name       = "tfstate"
   key                  = "resume-optimizer/dev/terraform.tfstate"
   use_azuread_auth     = true # no shared key needed
 }
}
