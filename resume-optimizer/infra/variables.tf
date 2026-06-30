
variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "centralus"
}

variable "prefix" {
  description = "Short prefix for resource names (3-8 lowercase alphanumeric chars, must be globally unique for storage/keyvault)"
  type        = string
  default     = "resumeai"

  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.prefix))
    error_message = "Prefix must be 3-8 lowercase alphanumeric characters with no hyphens."
  }
}

variable "environment" {
  description = "Environment tag (dev / staging / prod)"
  type        = string
  default     = "dev"
}

# ── PostgreSQL ────────────────────────────────────────────────────────────────

variable "postgres_admin_login" {
  description = "PostgreSQL admin username"
  type        = string
  default     = "resumeadmin"
}

variable "postgres_db_name" {
  description = "Name of the application database"
  type        = string
  default     = "resumeopt"
}

variable "postgres_sku" {
  description = "PostgreSQL Flexible Server SKU (student account: Standard_B1ms ~$12/mo)"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "PostgreSQL storage in MB"
  type        = number
  default     = 32768 # 32 GB (minimum)
}

variable "postgres_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "16"
}

# ── App Service ───────────────────────────────────────────────────────────────

variable "app_service_sku" {
  description = "App Service Plan SKU (student account: B1 ~$13/mo)"
  type        = string
  default     = "B1"
}

# ── API keys / secrets ────────────────────────────────────────────────────────
# Externally-sourced secrets (all API keys, Stripe, BOOTSTRAP-SECRET) are NO LONGER
# Terraform variables. They are seeded directly into Key Vault out-of-band (see
# seed-secrets.sh) so rotation never requires a terraform apply. Terraform only
# manages secrets it derives from infra it owns (JWT-SECRET, DATABASE-URL).

# ── Non-secret model toggles (plain App Service settings) ─────────────────────

variable "model_optimizer" {
  description = "LiteLLM model for the Phase-2 strategist. Env-overridable for rollback."
  type        = string
  default     = "deepseek/deepseek-v4-pro"
}

variable "deepseek_reasoning_effort" {
  description = "DeepSeek V4 thinking effort: max | high"
  type        = string
  default     = "max"
}

# ── Blob lifecycle / retention ────────────────────────────────────────────────

variable "output_blob_retention_days" {
  description = "Days after last modification before blobs in the outputs container are auto-deleted. Generated .docx files are ephemeral once downloaded."
  type        = number
  default     = 30

  validation {
    condition     = var.output_blob_retention_days >= 1
    error_message = "Retention must be at least 1 day."
  }
}

variable "delta_blob_retention_days" {
  description = "Days after last modification before Delta Lake data-partition blobs are auto-deleted. Acts as a safety net; the application-level vacuum_old_matches() is the primary cleanup path. Must be >= the application retention window (90 days)."
  type        = number
  default     = 90

  validation {
    condition     = var.delta_blob_retention_days >= 7
    error_message = "Delta retention must be at least 7 days to avoid deleting active partitions."
  }
}
