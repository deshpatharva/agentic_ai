# Environment Upgrade Guide

This guide covers promoting a release from `dev` → `staging` → `prod` after dev
testing rounds are complete. Run through this checklist before each promotion.

---

## Pre-Promotion Checklist (do before every upgrade)

- [ ] All CI checks passing on `main`
- [ ] Dev smoke test passed: register, login, run a resume optimization end-to-end
- [ ] No stuck jobs in the admin dashboard (`/admin/stats`)
- [ ] Key Vault secrets up to date in current env (no empty values)
- [ ] Any new Alembic migrations tested locally against PostgreSQL (not just SQLite)

---

## Part 1 — Provision the Target Environment with Terraform

Each environment (staging, prod) needs its own infrastructure. Run the Terraform
workflow once per environment before any app deploy.

### 1a — Bootstrap the TFState storage account (first time only per env)

This step is only needed the first time you provision a new environment. Skip it if
the env already has infrastructure.

```bash
cd resume-optimizer/infra
az login
az account set --subscription "<your-subscription-id>"

# Create the resource group for the target env (staging or prod)
az group create --name resumeai-rg-<env> --location centralus

# Bootstrap with local state
terraform init -backend=false

terraform apply \
  -target=azurerm_storage_account.tfstate \
  -target=azurerm_storage_container.tfstate \
  -target=azurerm_role_assignment.terraform_tfstate \
  -var="environment=<env>" \
  -var="google_ai_api_key=placeholder" \
  -var="groq_api_key=placeholder" \
  -var="anthropic_api_key=placeholder" \
  -var="bootstrap_secret=placeholder"

# Migrate to remote backend
terraform init -migrate-state \
  -backend-config="resource_group_name=resumeai-rg-<env>" \
  -backend-config="storage_account_name=resumeaitfst<suffix>" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=resume-optimizer/<env>/terraform.tfstate" \
  -backend-config="use_azuread_auth=true"
```

TFState storage account names by environment:
| Environment | Storage account name |
|-------------|---------------------|
| dev | `resumeaitfstdevnp` |
| staging | `resumeaitfststgnp` |
| prod | `resumeaitfstprodp` |

Grant SP access to the new env's TFState account:
```bash
az role assignment create \
  --assignee-object-id "<SP_OBJECT_ID>" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/<SUB>/resourceGroups/resumeai-rg-<env>/providers/Microsoft.Storage/storageAccounts/resumeaitfst<suffix>"
```

### 1b — Run the Terraform workflow

1. GitHub → Actions → **Terraform** → Run workflow
2. Select: **environment = `staging`** (or `prod`), **action = `plan-only`**
3. Review the plan — verify no unexpected destroys
4. Run again: same environment, **action = `apply`**
5. Wait for apply to complete (~15–25 min first time, ~5 min for updates)

---

## Part 2 — Capture Outputs and Update GitHub Secrets

After each Terraform apply, two values change per environment:

```bash
cd resume-optimizer/infra

terraform init \
  -backend-config="resource_group_name=resumeai-rg-<env>" \
  -backend-config="storage_account_name=resumeaitfst<suffix>" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=resume-optimizer/<env>/terraform.tfstate" \
  -backend-config="use_azuread_auth=true"

terraform output -raw static_web_app_deployment_token
terraform output backend_url
```

Update these GitHub secrets before deploying:

| Secret | Value |
|--------|-------|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | from `terraform output -raw static_web_app_deployment_token` |
| `AZURE_WEBAPP_NAME` | `resumeai-api-<env>` (e.g. `resumeai-api-staging`) |

> **Note:** These secrets are shared across environments in the current setup.
> Update them to point at the target environment before running deploy workflows,
> and restore them afterward if needed.

---

## Part 3 — Run Database Migrations

Migrations must run before the app starts serving traffic in the new environment.
PostgreSQL is VNet-private — run via App Service SSH.

```bash
az webapp ssh \
  --resource-group resumeai-rg-<env> \
  --name resumeai-api-<env>
```

Inside the SSH session:
```bash
cd /home/site/wwwroot
python -m alembic upgrade head
```

Verify migrations applied:
```bash
python -m alembic current   # should show head revision
```

---

## Part 4 — Deploy Backend

GitHub → Actions → **Deploy — Backend** → Run workflow

The workflow deploys whatever is on `main` to the App Service named in
`AZURE_WEBAPP_NAME`. Verify the secret points at the correct environment before
triggering.

Wait for the deploy to complete, then check the app is up:
```bash
curl https://resumeai-api-<env>.azurewebsites.net/health
```

---

## Part 5 — Deploy Frontend

GitHub → Actions → **Deploy — Frontend** → Run workflow

The build injects `VITE_API_URL` from `AZURE_WEBAPP_NAME` at compile time, so the
frontend bundle will point at whichever App Service URL is in that secret.

After deploy, open the Static Web Apps URL from Terraform outputs and verify the
frontend loads and can reach the backend.

---

## Part 6 — Bootstrap Admin Account (first time per env only)

First time you provision a new environment, no admin exists yet.

```bash
# Register your account
curl -X POST https://resumeai-api-<env>.azurewebsites.net/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"your@email.com","password":"YourPassword1","full_name":"Your Name"}'

# Promote to admin (one-time — fails if admin already exists)
curl -X POST https://resumeai-api-<env>.azurewebsites.net/admin/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"your@email.com","secret":"<BOOTSTRAP_SECRET value>"}'
```

---

## Part 7 — Verification

- [ ] `GET /health` returns 200
- [ ] Frontend loads at the Static Web Apps URL
- [ ] Can register and log in
- [ ] Run one full resume optimization end-to-end
- [ ] Check admin dashboard stats load (`/admin/stats`)
- [ ] No errors in App Service logs:
  ```bash
  az webapp log tail --resource-group resumeai-rg-<env> --name resumeai-api-<env>
  ```

---

## Resource Names by Environment

| Resource | dev | staging | prod |
|----------|-----|---------|------|
| Resource Group | `resumeai-rg-dev` | `resumeai-rg-staging` | `resumeai-rg-prod` |
| App Service | `resumeai-api-dev` | `resumeai-api-staging` | `resumeai-api-prod` |
| PostgreSQL | `resumeai-pg-dev` | `resumeai-pg-staging` | `resumeai-pg-prod` |
| Key Vault | `resumeaikvdevnp` | `resumeaikvstgnp` | `resumeaikvprodp` |
| Storage | `resumeaistdevnp` | `resumeaiststgnp` | `resumeaistprodp` |
| TFState | `resumeaitfstdevnp` | `resumeaitfststgnp` | `resumeaitfstprodp` |
| Static Web App | `resumeai-web-dev` | `resumeai-web-staging` | `resumeai-web-prod` |
