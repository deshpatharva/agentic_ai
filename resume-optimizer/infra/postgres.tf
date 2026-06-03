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

  delegated_subnet_id = azurerm_subnet.postgres.id
  private_dns_zone_id = azurerm_private_dns_zone.postgres.id

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

# ── Firewall — Private access mode (delegated subnet) ─────────────────────────
# With delegated_subnet_id configured above, the server is in private-access mode:
# no public IP is assigned, and no firewall rules (IP-based) apply.
# The App Service connects via private VNet integration (app_service.tf).
# To access Postgres from outside the VNet (e.g. local dev psql), use the
# bastion pattern or SSH tunnel to a jump host inside the VNet.

# ── PostgreSQL extensions ─────────────────────────────────────────────────────

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "UUID-OSSP,PG_TRGM"
}
