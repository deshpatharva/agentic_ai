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
# SECURITY NOTE — prod tightening required:
#
# The 0.0.0.0/0.0.0.0 rule is Azure's magic sentinel for "Allow access to Azure
# services", but it opens the server to EVERY resource in Azure across ALL
# tenants and subscriptions — not just our App Service.  Any other Azure customer
# can attempt a connection from their IP if they know the hostname and credentials.
#
# For dev this is acceptable; for staging/prod replace with one of:
#   a) VNet Integration: add the App Service to a VNet subnet, replace this rule
#      with azurerm_postgresql_flexible_server_virtual_network_rule pointing at
#      that subnet, and enable the service endpoint "Microsoft.Sql" on the subnet.
#   b) Private Endpoint: provision azurerm_private_endpoint for the Postgres
#      server inside a VNet subnet; disable public network access entirely
#      (public_network_access_enabled = false on the server).
#
# Both options require an azurerm_virtual_network and at least one subnet, which
# are not provisioned here.  Track as a prod prerequisite before going live.

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
