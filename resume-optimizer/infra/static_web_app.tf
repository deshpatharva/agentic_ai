# ── Static Web Apps (React frontend) ─────────────────────────────────────────
# Free tier — $0/mo, custom domains supported, global CDN
# azurerm 4.x: sku_tier and sku_size were removed; Free is the implicit default.

resource "azurerm_static_web_app" "frontend" {
  name                = local.static_web_app_name
  resource_group_name = azurerm_resource_group.main.name
  location            = "eastus2" # Static Web Apps region availability varies; eastus2 is reliable

  tags = local.tags
}
