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

  # System-Assigned Managed Identity — the app's credential for KV and Storage.
  # No client secret is injected into the environment.
  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on = true # Required: keeps the worker alive for SSE streams and in-flight pipeline jobs

    application_stack {
      python_version = "3.11"
    }

    app_command_line = "uvicorn main:app --host 0.0.0.0 --port 8000"

    cors {
      allowed_origins     = ["https://${azurerm_static_web_app.frontend.default_host_name}"]
      support_credentials = true
    }
  }

  # Only non-secret bootstrap values.  The MI authenticates to Key Vault at
  # runtime; config.py fetches every other secret from there.
  # AZURE_CLIENT_ID and AZURE_TENANT_ID are kept so config.py can fall back to
  # ClientSecretCredential on local dev (where MI is unavailable); on App
  # Service, DefaultAzureCredential will prefer the MI automatically.
  app_settings = {
    AZURE_TENANT_ID = data.azurerm_client_config.current.tenant_id
    AZURE_CLIENT_ID = data.azuread_application.app.client_id
    KEY_VAULT_URL   = azurerm_key_vault.main.vault_uri

    SCM_DO_BUILD_DURING_DEPLOYMENT     = "true"
    WEBSITES_PORT                      = "8000"
    WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"
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
