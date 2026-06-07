variable "subscription_id" {
  description = "Azure subscription ID (find with: az account show --query id -o tsv)"
  type        = string
}

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

# ── API Keys (written to Key Vault at provision time) ─────────────────────────

variable "google_ai_api_key" {
  description = "Google AI Studio API key (Gemini) — required, no default"
  type        = string
  sensitive   = true
}

variable "groq_api_key" {
  description = "Groq API key — required, no default"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key — required, no default"
  type        = string
  sensitive   = true
}

variable "adzuna_app_id" {
  description = "Adzuna job scraper App ID (optional)"
  type        = string
  sensitive   = true
  default     = "REPLACE_ME"
}

variable "adzuna_app_key" {
  description = "Adzuna job scraper App Key (optional)"
  type        = string
  sensitive   = true
  default     = "REPLACE_ME"
}

variable "the_muse_api_key" {
  description = "The Muse API key (optional)"
  type        = string
  sensitive   = true
  default     = "REPLACE_ME"
}

variable "apify_token" {
  description = "Apify token for LinkedIn scraper (optional, paid)"
  type        = string
  sensitive   = true
  default     = "REPLACE_ME"
}

variable "stripe_secret_key" {
  description = "Stripe secret key (optional, for billing)"
  type        = string
  sensitive   = true
  default     = "REPLACE_ME"
}

variable "client_id" {
  type        = string
  description = "The Application (client) ID of the existing App Registration"
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
