# ── Virtual Network ───────────────────────────────────────────────────────────

resource "azurerm_virtual_network" "main" {
  name                = "${local.prefix}-vnet"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.0.0.0/16"]
  tags                = local.tags
}

# ── Postgres subnet — delegated to PostgreSQL Flexible Server ─────────────────
# Flexible Server requires a dedicated delegated subnet; no other resources
# can be deployed into this subnet.

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# ── App Service subnet ────────────────────────────────────────────────────────
# Regional VNet integration requires a dedicated subnet delegated to
# Microsoft.Web/serverFarms. Minimum /27 (32 addresses) recommended.

resource "azurerm_subnet" "app_service" {
  name                 = "app-service"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "app-service-delegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

# ── Private DNS zone for Postgres ─────────────────────────────────────────────
# Required for Flexible Server private access.
# Inside the VNet, <server>.postgres.database.azure.com resolves to the
# server's private IP via this zone — DATABASE_URL in Key Vault is unchanged.

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "${local.prefix}-postgres-dns-link"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.tags
}
