# import {
#   to = azurerm_resource_group.main
#   id = "/subscriptions/6beb02cf-15a2-4da3-bf0d-e18eeb75d08b/resourceGroups/resumeai-rg-dev"
# }
resource "azurerm_resource_group" "main" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
}
