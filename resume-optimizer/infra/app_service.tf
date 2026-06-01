# ── App Service Plan (Linux, Python) ─────────────────────────────────────────

resource "azurerm_service_plan" "main" {
  name                = local.app_service_plan_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku  # B1 ~$13/mo on student credit

  tags = local.tags
}

# ── App Service (FastAPI backend) ─────────────────────────────────────────────

resource "azurerm_linux_web_app" "backend" {
  name                = local.app_service_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id

  https_only = true

  site_config {
    always_on = false  # Must be false on B1 (Basic tier)

    application_stack {
      python_version = "3.11"
    }

    # FastAPI startup command
    app_command_line = "uvicorn main:app --host 0.0.0.0 --port 8000"

    cors {
      allowed_origins     = ["https://${azurerm_static_web_app.frontend.default_host_name}"]
      support_credentials = true
    }
  }

  # ── App settings: only the 4 values the SP needs to boot ─────────────────
  # The Python app reads these at startup and fetches everything else from KV

  app_settings = {
    # Service Principal — used by config.py to authenticate to Key Vault + Storage
    AZURE_TENANT_ID     = data.azurerm_client_config.current.tenant_id
    AZURE_CLIENT_ID     = azuread_application.app.client_id
    AZURE_CLIENT_SECRET = azuread_service_principal_password.app.value
    KEY_VAULT_URL       = azurerm_key_vault.main.vault_uri

    # Python / App Service
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    WEBSITES_PORT                  = "8000"

    # Disable default Azure logging noise
    WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.sp_kv_secrets_user,
    azurerm_role_assignment.sp_storage_contributor,
  ]
}
