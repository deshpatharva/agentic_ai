# ── PostgreSQL Flexible Server ────────────────────────────────────────────────

resource "azurerm_postgresql_flexible_server" "main" {
  name                   = local.postgres_server_name
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = var.postgres_version
  administrator_login    = var.postgres_admin_login
  administrator_password = random_password.postgres_password.result
  sku_name               = var.postgres_sku        # Standard_B1ms — cheapest, ~$12/mo
  storage_mb             = var.postgres_storage_mb # 32 GB minimum
  zone                   = "1"

  # High availability disabled for dev/student (adds cost)
  high_availability {
    mode = "Disabled"
  }

  # Backups: 7 days, geo-redundant off (reduces cost on student account)
  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  tags = local.tags
}

# ── Application database ──────────────────────────────────────────────────────

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.postgres_db_name
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# ── Firewall — allow Azure services (App Service) ─────────────────────────────

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ── Firewall — allow your local dev machine ───────────────────────────────────
# Uncomment and set your local IP to connect from your laptop
# resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_local" {
#   name             = "AllowLocalDev"
#   server_id        = azurerm_postgresql_flexible_server.main.id
#   start_ip_address = "YOUR.LOCAL.IP.ADDRESS"
#   end_ip_address   = "YOUR.LOCAL.IP.ADDRESS"
# }

# ── PostgreSQL extensions ─────────────────────────────────────────────────────

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "UUID-OSSP,PG_TRGM"
}
