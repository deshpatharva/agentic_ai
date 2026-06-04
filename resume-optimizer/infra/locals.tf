locals {
  # Common tags applied to every resource
  tags = {
    project     = "resume-optimizer"
    environment = var.environment
    managed_by  = "terraform"
  }

  # Prefix for resource naming — imported from variables for consistency
  prefix = local.prefix

  # Resource names — centralised here so changes ripple everywhere.
  #
  # Key Vault and Storage Account names must be globally unique across all of
  # Azure, so a random 6-char suffix is appended.  All other names are scoped
  # to the subscription/resource-group and don't need the suffix.
  resource_group_name   = "${local.prefix}-rg-${var.environment}"
  key_vault_name        = "${local.prefix}kv${var.environment}${random_string.suffix.result}"  # max 24 chars
  storage_account_name  = "${local.prefix}st${var.environment}${random_string.suffix.result}"  # max 24 chars, lowercase alphanumeric
  postgres_server_name  = "${local.prefix}-pg-${var.environment}"
  app_service_plan_name = "${local.prefix}-asp-${var.environment}"
  app_service_name      = "${local.prefix}-api-${var.environment}"
  static_web_app_name   = "${local.prefix}-web-${var.environment}"
  sp_app_name           = "${local.prefix}-sp-${var.environment}"

  # Blob container names
  uploads_container = "uploads"
  outputs_container = "outputs"
  delta_container   = "delta"

  # Delta Lake path written into Key Vault
  delta_storage_path = "az://${local.delta_container}/delta/"
}
