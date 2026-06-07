# ── Log Analytics Workspace ───────────────────────────────────────────────────
# Receives App Service console logs (structured JSON stdout) and HTTP access logs.
# 7-day retention keeps costs near zero on student credit.
# PerGB2018: first 5 GB/month free, ~$2.30/GB after.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.prefix}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 7
  tags                = local.tags
}

# ── Diagnostic Setting — App Service → Log Analytics ─────────────────────────
# AppServiceConsoleLogs: stdout/stderr from the Python process (our JSON logs).
# AppServiceHTTPLogs:    platform-level HTTP access log (redundant backup).

resource "azurerm_monitor_diagnostic_setting" "app_service" {
  name                       = "${local.prefix}-app-diag"
  target_resource_id         = azurerm_linux_web_app.backend.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "AppServiceConsoleLogs"
  }

  enabled_log {
    category = "AppServiceHTTPLogs"
  }
}
