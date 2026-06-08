# First-Time Deployment Guide — Dev Environment

This guide covers everything needed to bring up the resume-optimizer stack for the
first time in the `dev` environment. Follow the parts in order — each part has
dependencies on the previous one.

**Stack:** FastAPI backend (Azure App Service) + React/Vite frontend (Azure Static Web
Apps) + PostgreSQL Flexible Server (private VNet) + Key Vault + Storage Account.

**Time estimate:** ~45–60 minutes, mostly waiting on Azure provisioning.

---

## Prerequisites

### Local tools
| Tool | Version | Install |
|------|---------|---------|
| Azure CLI | 2.x | `winget install Microsoft.AzureCLI` |
| Terraform | ≥ 1.5 | `winget install Hashicorp.Terraform` |
| Git | any | already installed |
| Python | 3.11 | only needed for secret generation |

### Accounts and API keys — gather before starting
- Azure subscription (active, with budget/student credits)
- GitHub repo with admin access
- **Anthropic API key** (`sk-ant-...`) — required, drives resume optimization
- **Google AI Studio API key** (`AIza...`) — required, drives most model calls
- **Groq API key** (`gsk_...`) — required, drives the humanizer critic

---

## Part 1 — Azure: Create the OIDC Service Principal

This is a one-time manual step. The service principal (SP) is the identity GitHub
Actions uses to authenticate to Azure without storing a password.

```bash
SUBSCRIPTION_ID="<your-subscription-id>"
SP_NAME="resume-optimizer-github-sp"

# Create the SP with Contributor on the subscription
az ad sp create-for-rbac \
  --name "$SP_NAME" \
  --role Contributor \
  --scopes "/subscriptions/$SUBSCRIPTION_ID" \
  --sdk-auth false

# Save from the output:
#   appId   → CLIENT_ID
#   tenant  → TENANT_ID
# The password field is NOT used (OIDC has no client secret).
```

Get the SP object ID (needed later for role assignments):

```bash
CLIENT_ID="<appId from above>"
SP_OBJECT_ID=$(az ad sp show --id "$CLIENT_ID" --query id -o tsv)
echo "SP_OBJECT_ID: $SP_OBJECT_ID"
```

### Create federated credentials for GitHub Actions

OIDC works by matching the GitHub Actions JWT subject to a registered credential.
You need one credential per GitHub environment used.

Replace `<owner>/<repo>` with your actual GitHub org/repo name.

```bash
APP_OBJECT_ID=$(az ad app show --id "$CLIENT_ID" --query id -o tsv)

# For the Terraform workflow — maps to GitHub environment "dev"
az ad app federated-credential create \
  --id "$APP_OBJECT_ID" \
  --parameters '{
    "name": "github-terraform-dev",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:<owner>/<repo>:environment:dev",
    "audiences": ["api://AzureADTokenAudience"]
  }'

# For the deploy workflows — maps to GitHub environment "production"
az ad app federated-credential create \
  --id "$APP_OBJECT_ID" \
  --parameters '{
    "name": "github-deploy-production",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:<owner>/<repo>:environment:production",
    "audiences": ["api://AzureADTokenAudience"]
  }'
```

> **Why two credentials?** `terraform.yml` uses the `dev` environment; `deploy-backend.yml`
> and `deploy-frontend.yml` both use the `production` environment. Each environment
> gets its own OIDC subject string.

---

## Part 2 — GitHub: Configure Environments, Secrets, and Variables

### 2a — Create GitHub environments

Go to **GitHub repo → Settings → Environments → New environment**.

Create these two environments:
- `dev` — no protection rules needed
- `production` — optionally add required reviewers before deploys

### 2b — Repository secrets

Go to **Settings → Secrets and variables → Actions → Secrets**.

| Secret name | Value |
|-------------|-------|
| `AZURE_CLIENT_ID` | SP `appId` from Part 1 |
| `AZURE_TENANT_ID` | Azure tenant ID from Part 1 |
| `AZURE_SUBSCRIPTION_ID` | Your subscription ID |
| `TF_VAR_ANTHROPIC_API_KEY` | Your Anthropic API key |
| `TF_VAR_GOOGLE_AI_API_KEY` | Your Google AI Studio API key |
| `TF_VAR_GROQ_API_KEY` | Your Groq API key |
| `TF_VAR_BOOTSTRAP_SECRET` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |

> `TF_VAR_BOOTSTRAP_SECRET` is a one-time secret used for initial admin setup in the
> app. Generate it once, store it somewhere safe (e.g. a password manager), and never
> change it unless you need to rotate it.

### 2c — Repository variables

Go to **Settings → Secrets and variables → Actions → Variables**.

| Variable name | Value |
|---------------|-------|
| `AZURE_CLIENT_ID` | Same SP `appId` |
| `AZURE_TENANT_ID` | Same tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Same subscription ID |

> **Why both secret and variable?** `terraform.yml` reads `secrets.AZURE_CLIENT_ID`
> (OIDC token exchange requires it in secrets). `deploy-backend.yml` and
> `deploy-frontend.yml` read `vars.AZURE_CLIENT_ID` (non-sensitive GUID). Both must
> be set.

> **`AZURE_WEBAPP_NAME` and `AZURE_STATIC_WEB_APPS_API_TOKEN`** are set in Part 6,
> after Terraform creates the resources.

---

## Part 3 — Bootstrap: Create the TFState Storage Account

Terraform state must be stored somewhere before Terraform can manage itself. This
two-step bootstrap creates the state storage account with local state, then migrates
to remote state.

Run these commands from your local machine, logged in as **yourself** (not the SP).

```bash
cd resume-optimizer/infra

# Log in as your personal Azure account
az login
az account set --subscription "<your-subscription-id>"

# Create the resource group (Terraform manages it later, but it must exist for bootstrap)
az group create --name resumeai-rg-dev --location centralus
```

**Step 1 — Initialize with local state and apply only the 3 bootstrap resources:**

```bash
terraform init -backend=false

terraform apply \
  -target=azurerm_storage_account.tfstate \
  -target=azurerm_storage_container.tfstate \
  -target=azurerm_role_assignment.terraform_tfstate \
  -var="google_ai_api_key=placeholder" \
  -var="groq_api_key=placeholder" \
  -var="anthropic_api_key=placeholder" \
  -var="bootstrap_secret=placeholder"
```

> The placeholder values for the API keys and bootstrap_secret are fine here — these
> 3 resources don't use them. You'll supply real values via GitHub secrets when the
> full infra apply runs.

**Step 2 — Migrate to the remote backend:**

```bash
terraform init -migrate-state \
  -backend-config="resource_group_name=resumeai-rg-dev" \
  -backend-config="storage_account_name=resumeaitfstdevnp" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=resume-optimizer/dev/terraform.tfstate" \
  -backend-config="use_azuread_auth=true"
```

When prompted `Do you want to copy existing state to the new backend?` → type `yes`.

You can now delete the local `terraform.tfstate` file — state lives in Azure.

### Grant the SP access to the TFState storage account

The SP (GitHub Actions identity) needs blob read/write access to the state account.
Your personal `az login` session won't be active in CI.

```bash
az role assignment create \
  --assignee-object-id "$SP_OBJECT_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/resumeai-rg-dev/providers/Microsoft.Storage/storageAccounts/resumeaitfstdevnp"
```

---

## Part 4 — Deploy Infrastructure via GitHub Actions

1. Go to **GitHub → Actions → Terraform** workflow
2. Click **Run workflow**
3. Select: **environment = `dev`**, **action = `plan-only`**
4. Click **Run workflow** and wait (~2 minutes)
5. Open the completed run and expand the **Terraform Plan** step — review what will be created
6. If the plan looks correct, run again: **environment = `dev`**, **action = `apply`**
7. Wait for the apply to complete — **first-time provisioning takes 15–25 minutes**
   (PostgreSQL Flexible Server takes the longest)

> The apply job uses the `dev` GitHub environment. If you added required reviewers,
> approve the deployment when GitHub prompts.

> **If the apply fails partway:** just re-run `apply`. The idempotent import step at
> the start of each run will import already-created resources into state, and the
> remaining resources will be created.

---

## Part 5 — Capture Terraform Outputs

After a successful apply, retrieve the outputs. Either use the workflow run logs
(look for the Plan step output), or run locally:

```bash
cd resume-optimizer/infra

terraform init \
  -backend-config="resource_group_name=resumeai-rg-dev" \
  -backend-config="storage_account_name=resumeaitfstdevnp" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=resume-optimizer/dev/terraform.tfstate" \
  -backend-config="use_azuread_auth=true"

# Show all outputs
terraform output

# Get the sensitive deploy token (needed in Part 6)
terraform output -raw static_web_app_deployment_token
```

Note the values for:
- `backend_url` — e.g. `https://resumeai-api-dev.azurewebsites.net`
- `frontend_url` — Static Web Apps URL
- `static_web_app_deployment_token` — secret, used by the frontend deploy workflow

---

## Part 6 — Set Remaining GitHub Secrets and Variables

Now that the infrastructure exists, add these:

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret name | Value |
|-------------|-------|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | From `terraform output -raw static_web_app_deployment_token` |

**Variables** (Settings → Secrets and variables → Actions → Variables):

| Variable name | Value |
|---------------|-------|
| `AZURE_WEBAPP_NAME` | `resumeai-api-dev` |

---

## Part 7 — Run Database Migrations

PostgreSQL is in a private VNet with no public access. You cannot connect from your
local machine or from a standard GitHub Actions runner. Run Alembic migrations through
the App Service SSH console instead.

**Option A — Azure Portal:**
1. Go to **Azure Portal → App Services → resumeai-api-dev**
2. Under **Development Tools**, click **SSH**
3. A browser-based SSH session opens into the app container

**Option B — Azure CLI:**
```bash
az webapp ssh \
  --resource-group resumeai-rg-dev \
  --name resumeai-api-dev
```

**Inside the SSH session:**
```bash
cd /home/site/wwwroot
python -m alembic upgrade head
```

> If the app hasn't deployed yet, the SSH session will be inside a placeholder
> container with no code. Deploy the backend first (Part 8), wait for it to finish,
> then run migrations.

---

## Part 8 — Deploy the Backend

The deploy workflow packages `resume-optimizer/backend/` and deploys it to App
Service via Oryx. Oryx runs `pip install -r requirements.txt` and starts the app
with `uvicorn main:app --host 0.0.0.0 --port 8000`.

**Option A — Automatic:** Push any change to `resume-optimizer/backend/**` or
`resume-optimizer/requirements.txt` on the `main` branch.

**Option B — Manual:**
1. **GitHub → Actions → Deploy — Backend → Run workflow**
2. No inputs needed — click **Run workflow**
3. The `production` environment gate will activate — approve if required reviewers
   are configured

The first deploy takes ~5–10 minutes (Oryx installs all Python dependencies including
spaCy models). Subsequent deploys are faster due to pip caching.

---

## Part 9 — Deploy the Frontend

The frontend deploy workflow builds the React/Vite app and uploads it to Azure Static
Web Apps. The build injects `VITE_API_URL=https://resumeai-api-dev.azurewebsites.net`
at compile time so the compiled JS bundle points at the correct backend.

**Option A — Automatic:** Push any change to `resume-optimizer/frontend/**` on `main`.

**Option B — Manual:**
1. **GitHub → Actions → Deploy — Frontend → Run workflow**
2. Click **Run workflow**

The build + upload usually takes 2–3 minutes.

---

## Part 10 — Verification

### Backend health check
```bash
curl https://resumeai-api-dev.azurewebsites.net/health
# Expected: 200 OK with {"status": "ok"} or similar
```

### Frontend
Open the `frontend_url` from Terraform outputs in a browser. The React app should
load and be able to reach the backend.

### App Service logs
```bash
az webapp log tail \
  --resource-group resumeai-rg-dev \
  --name resumeai-api-dev
```

Or check the Log Analytics workspace in Azure Portal:
**Azure Portal → Log Analytics Workspaces → resumeai-law-dev → Logs**

### Key Vault secret resolution
If the app starts but returns 500 errors, Key Vault secret references may not have
resolved yet. Check in the portal:
**App Service → Configuration → Application settings** — each `@Microsoft.KeyVault`
entry should show a green checkmark. If not, verify the Managed Identity has the
`Key Vault Secrets User` role on the vault (assigned by Terraform).

---

## Reference: Resource Names (Dev)

| Resource | Name |
|----------|------|
| Resource Group | `resumeai-rg-dev` |
| TFState Storage Account | `resumeaitfstdevnp` |
| App Storage Account | `resumeaistdevnp` |
| Key Vault | `resumeaikvdevnp` |
| App Service Plan | `resumeai-asp-dev` |
| App Service (backend) | `resumeai-api-dev` |
| PostgreSQL Server | `resumeai-pg-dev` |
| Static Web App (frontend) | `resumeai-web-dev` |

## Reference: GitHub Secrets and Variables Checklist

| Type | Name | When set |
|------|------|----------|
| Secret | `AZURE_CLIENT_ID` | Part 2 |
| Secret | `AZURE_TENANT_ID` | Part 2 |
| Secret | `AZURE_SUBSCRIPTION_ID` | Part 2 |
| Secret | `TF_VAR_ANTHROPIC_API_KEY` | Part 2 |
| Secret | `TF_VAR_GOOGLE_AI_API_KEY` | Part 2 |
| Secret | `TF_VAR_GROQ_API_KEY` | Part 2 |
| Secret | `TF_VAR_BOOTSTRAP_SECRET` | Part 2 |
| Secret | `AZURE_STATIC_WEB_APPS_API_TOKEN` | Part 6 (after TF apply) |
| Variable | `AZURE_CLIENT_ID` | Part 2 |
| Variable | `AZURE_TENANT_ID` | Part 2 |
| Variable | `AZURE_SUBSCRIPTION_ID` | Part 2 |
| Variable | `AZURE_WEBAPP_NAME` | Part 6 (after TF apply) |

## Reference: Workflow Summary

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `terraform.yml` | Manual (`workflow_dispatch`) | Plan and apply infrastructure changes |
| `deploy-backend.yml` | Push to `main` / manual | Deploy FastAPI backend to App Service |
| `deploy-frontend.yml` | Push to `main` / manual | Build and deploy React frontend to Static Web Apps |
| `ci.yml` | Push to `main` / PR to `main` | Lint, smoke tests, migration check |
