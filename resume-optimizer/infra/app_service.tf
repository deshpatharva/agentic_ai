# ── App Service Plan (Linux, Python) ─────────────────────────────────────────

resource "azurerm_service_plan" "main" {
  name                = local.app_service_plan_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku # B1 ~$13/mo on student credit

  tags = local.tags
}

# ── App Service (FastAPI backend) ─────────────────────────────────────────────

resource "azurerm_linux_web_app" "backend" {
  name                = local.app_service_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id

  https_only = true

  virtual_network_subnet_id = azurerm_subnet.app_service.id

  # System-Assigned Managed Identity — the app's credential for KV and Storage.
  # No client secret is injected into the environment.
  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on = true # Required: keeps the worker alive for SSE streams and in-flight pipeline jobs

    application_stack {
      python_version = "3.12"
    }

    app_command_line = "uvicorn main:app --host 0.0.0.0 --port 8000"

    cors {
      allowed_origins     = ["https://${azurerm_static_web_app.frontend.default_host_name}"]
      support_credentials = true
    }
  }

  # ── App Service logging ───────────────────────────────────────────────────
  # REQUIRED for the AppServiceConsoleLogs diagnostic category to receive data.
  # On Linux App Service, container stdout/stderr is only captured when
  # application logging is enabled here; without this block logging defaults to
  # Off and the Log Analytics workspace stays empty despite the diagnostic
  # setting in monitoring.tf. file_system_level surfaces our JSON stdout logs.
  logs {
    application_logs {
      file_system_level = "Information"
    }
    http_logs {
      file_system {
        retention_in_days = 7
        retention_in_mb   = 35
      }
    }
  }

  # ── Secrets resolved by App Service from Key Vault at startup ──────────────
  # App Service resolves @Microsoft.KeyVault(...) references before injecting
  # into the process environment. config.py sees plain os.environ values.
  app_settings = {
    # TF-managed secrets (derived from infra Terraform owns) — by resource reference.
    JWT_SECRET                 = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.jwt_secret.versionless_id})"
    DATABASE_URL               = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.database_url.versionless_id})"
    DELTA_STORAGE_PATH         = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.delta_storage_path.versionless_id})"
    AZURE_STORAGE_ACCOUNT_NAME = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.azure_storage_account_name.versionless_id})"

    # Externally-sourced secrets — seeded out-of-band (seed-secrets.sh), referenced
    # by name + versionless so rotations are picked up without a terraform apply.
    ANTHROPIC_API_KEY          = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=ANTHROPIC-API-KEY)"
    GOOGLE_AI_STUDIO_API_KEY   = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=GOOGLE-AI-STUDIO-API-KEY)"
    GROQ_API_KEY               = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=GROQ-API-KEY)"
    DEEPSEEK_API_KEY           = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=DEEPSEEK-API-KEY)"
    BOOTSTRAP_SECRET           = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=BOOTSTRAP-SECRET)"
    STRIPE_SECRET_KEY          = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=STRIPE-SECRET-KEY)"
    ADZUNA_APP_ID              = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=ADZUNA-APP-ID)"
    ADZUNA_APP_KEY             = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=ADZUNA-APP-KEY)"
    THE_MUSE_API_KEY           = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=THE-MUSE-API-KEY)"
    APIFY_TOKEN                = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=APIFY-TOKEN)"

    # ── Non-secret bootstrap values ────────────────────────────────────────────
    SCM_DO_BUILD_DURING_DEPLOYMENT      = "true"
    ENABLE_ORYX_BUILD                   = "true" # required for OneDeploy API (azure/webapps-deploy@v3)
    WEBSITES_PORT                       = "8000"
    WEBSITES_CONTAINER_START_TIME_LIMIT = "1800" # spaCy + CrewAI import takes 500-700s on B1
    WEBSITE_SKIP_SECRETRESOLUTION_CACHE = "1"    # KV secret updates take effect immediately
    PYTHONUNBUFFERED                    = "1"    # flush stdout/stderr immediately so crash tracebacks appear in logs

    # ── Model toggles (override config.py defaults per-deployment, no code change) ─
    MODEL_OPTIMIZER           = var.model_optimizer
    DEEPSEEK_REASONING_EFFORT = var.deepseek_reasoning_effort
  }

  tags = local.tags
}

# ── Managed Identity → Key Vault Secrets User ─────────────────────────────────
# Grants the App Service's MI read access to all secrets in the vault.

resource "azurerm_role_assignment" "mi_kv_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_web_app.backend.identity[0].principal_id
}

# ── Managed Identity → Storage Blob Data Contributor ─────────────────────────
# Grants the App Service's MI read/write/delete on all containers.

resource "azurerm_role_assignment" "mi_storage_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_web_app.backend.identity[0].principal_id
}

# ── Managed Identity → Storage Blob Delegator ────────────────────────────────
# Required to call get_user_delegation_key() for generating SAS tokens.
# shared_access_key_enabled = false on the storage account means account-key
# SAS is not available; user delegation SAS is the only option.

resource "azurerm_role_assignment" "mi_storage_delegator" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_linux_web_app.backend.identity[0].principal_id
}
