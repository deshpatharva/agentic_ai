locals {
  # Common tags applied to every resource
  tags = {
    project     = "resume-optimizer"
    environment = var.environment
    managed_by  = "terraform"
  }

  # Resource names — centralised here so changes ripple everywhere.
  #
  # Key Vault and Storage Account names must be globally unique across all of
  # Azure, so a random 6-char suffix is appended.  All other names are scoped
  # to the subscription/resource-group and don't need the suffix.
  resource_group_name   = "${var.prefix}-rg-${var.environment}"
  key_vault_name        = "${var.prefix}kv${var.environment}${random_string.suffix.result}"  # max 24 chars
  storage_account_name  = "${var.prefix}st${var.environment}${random_string.suffix.result}"  # max 24 chars, lowercase alphanumeric
  postgres_server_name  = "${var.prefix}-pg-${var.environment}"
  app_service_plan_name = "${var.prefix}-asp-${var.environment}"
  app_service_name      = "${var.prefix}-api-${var.environment}"
  static_web_app_name   = "${var.prefix}-web-${var.environment}"
  sp_app_name           = "${var.prefix}-sp-${var.environment}"

  # Blob container names
  uploads_container = "uploads"
  outputs_container = "outputs"
  delta_container   = "delta"

  # Delta Lake path written into Key Vault
  delta_storage_path = "az://${local.delta_container}/delta/"
}
