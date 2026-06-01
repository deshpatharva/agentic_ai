# ── Static Web Apps (React frontend) ─────────────────────────────────────────
# Free tier — $0/mo, custom domains supported, global CDN

resource "azurerm_static_web_app" "frontend" {
  name                = local.static_web_app_name
  resource_group_name = azurerm_resource_group.main.name
  location            = "eastus2"  # Static Web Apps region availability varies; eastus2 is reliable
  sku_tier            = "Free"
  sku_size            = "Free"

  tags = local.tags
}
