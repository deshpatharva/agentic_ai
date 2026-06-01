locals {
  # Common tags applied to every resource
  tags = {
    project     = "resume-optimizer"
    environment = var.environment
    managed_by  = "terraform"
  }

  # Resource names — centralised here so changes ripple everywhere
  resource_group_name      = "${var.prefix}-rg-${var.environment}"
  key_vault_name           = "${var.prefix}kv${var.environment}"          # max 24 chars, no hyphens
  storage_account_name     = "${var.prefix}st${var.environment}"          # max 24 chars, globally unique
  postgres_server_name     = "${var.prefix}-pg-${var.environment}"
  app_service_plan_name    = "${var.prefix}-asp-${var.environment}"
  app_service_name         = "${var.prefix}-api-${var.environment}"
  static_web_app_name      = "${var.prefix}-web-${var.environment}"
  sp_app_name              = "${var.prefix}-sp-${var.environment}"

  # Blob container names
  uploads_container = "uploads"
  outputs_container = "outputs"
  delta_container   = "delta"

  # Constructed values used in Key Vault secrets
  delta_storage_path = "az://${local.delta_container}/delta/"
}
