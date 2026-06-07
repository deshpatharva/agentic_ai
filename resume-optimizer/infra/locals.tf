locals {
  # Common tags applied to every resource
  tags = {
    project     = "resume-optimizer"
    environment = var.environment
    managed_by  = "terraform"
  }

  # Environment suffix used in all globally-unique resource names.
  # No hyphens — Azure storage/keyvault names are lowercase alphanumeric only.
  # Logical names: dev-np → devnp, stg-np → stgnp, prod-p → prodp
  env_suffix = lookup({
    dev     = "devnp"
    staging = "stgnp"
    prod    = "prodp"
  }, var.environment, "${var.environment}np")

  # Resource names — centralised here so changes ripple everywhere.
  resource_group_name          = "${var.prefix}-rg-${var.environment}"
  key_vault_name               = "${var.prefix}kv${local.env_suffix}"   # max 24 chars
  storage_account_name         = "${var.prefix}st${local.env_suffix}"   # max 24 chars, lowercase alphanumeric
  tfstate_storage_account_name = "${var.prefix}tfst${local.env_suffix}" # max 24 chars
  postgres_server_name         = "${var.prefix}-pg-${var.environment}"
  app_service_plan_name        = "${var.prefix}-asp-${var.environment}"
  app_service_name             = "${var.prefix}-api-${var.environment}"
  static_web_app_name          = "${var.prefix}-web-${var.environment}"
  sp_app_name                  = "${var.prefix}-sp-${var.environment}"

  # Blob container names
  uploads_container = "uploads"
  outputs_container = "outputs"
  delta_container   = "delta"

  # Delta Lake path written into Key Vault
  delta_storage_path = "az://${local.delta_container}/delta/"
}
