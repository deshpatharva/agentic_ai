# CI/CD Setup Guide

Four GitHub Actions workflows gate and deploy this monorepo. No passwords or
API keys are ever stored in GitHub — Azure authentication uses OIDC federated
credentials, and the app reads its own runtime secrets from Key Vault via its
Managed Identity.

---

## Workflows

| File | Triggers | What it does |
|------|----------|-------------|
| `ci.yml` | push to `main` (app paths), any PR to `main` | Lint + smoke tests + frontend build |
| `deploy-backend.yml` | push to `main` (backend paths), `workflow_dispatch` | Deploys FastAPI to App Service via Oryx |
| `deploy-frontend.yml` | push to `main` (frontend paths), `workflow_dispatch` | Deploys React to Static Web Apps |
| `terraform.yml` | PR to `main` (infra paths), `workflow_dispatch` | Plans on PR; apply only on manual dispatch |

---

## Required GitHub Configuration

### 1. GitHub Environment

Create an environment named **`production`** in *Settings → Environments*:

- Enable **Required reviewers** — add at least one reviewer who must approve
  before any deploy or Terraform apply job executes.
- (Optional) Add a **deployment branch filter** to restrict to `main` only.

> The `environment: production` field in the deploy and terraform apply jobs
> means GitHub blocks those jobs until a reviewer clicks Approve.

---

### 2. Repository Variables (non-secret IDs)

Go to *Settings → Secrets and variables → Actions → Variables tab* and add:

| Variable | Value | How to get it |
|----------|-------|---------------|
| `AZURE_CLIENT_ID` | Service Principal client/app ID (GUID) | `terraform output service_principal_client_id` |
| `AZURE_TENANT_ID` | Azure AD tenant ID (GUID) | `terraform output tenant_id` |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID (GUID) | `az account show --query id -o tsv` |
| `AZURE_RESOURCE_GROUP` | Resource group name | `terraform output tfstate_resource_group_name` |
| `AZURE_WEBAPP_NAME` | App Service resource name | Value of `local.app_service_name` in `infra/locals.tf` (e.g. `resumeai-api-dev`) |

These are GUIDs/names with no secret value; storing them as **variables** (not
secrets) follows GitHub's own recommendation.

---

### 3. Repository Secrets

Go to *Settings → Secrets and variables → Actions → Secrets tab* and add:

| Secret | Value | How to get it |
|--------|-------|---------------|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | Static Web App deploy token | `terraform output static_web_app_deployment_token` |
| `TFSTATE_STORAGE_ACCOUNT_NAME` | State storage account name (has a random suffix) | `terraform output tfstate_storage_account_name` |
| `TF_VAR_GOOGLE_AI_API_KEY` | Google AI Studio API key | Google AI Studio console |
| `TF_VAR_GROQ_API_KEY` | Groq API key | Groq console |
| `TF_VAR_ANTHROPIC_API_KEY` | Anthropic API key | Anthropic console |

**Optional Terraform variable secrets** (uncomment the matching lines in
`terraform.yml` to enable):

| Secret | Variable |
|--------|----------|
| `TF_VAR_ADZUNA_APP_ID` | `adzuna_app_id` |
| `TF_VAR_ADZUNA_APP_KEY` | `adzuna_app_key` |
| `TF_VAR_THE_MUSE_API_KEY` | `the_muse_api_key` |
| `TF_VAR_APIFY_TOKEN` | `apify_token` |
| `TF_VAR_STRIPE_SECRET_KEY` | `stripe_secret_key` |

---

## OIDC Federated Identity Credentials

Authentication uses OIDC — no client secret is created or stored. The Terraform
in `infra/service_principal.tf` provisions two federated credentials on the
Service Principal's app registration:

| Credential | Subject | Used by |
|-----------|---------|---------|
| `github-main` | `repo:deshpatharva/agentic_ai:ref:refs/heads/main` | push-to-main jobs in deploy workflows |
| `github-env-production` | `repo:deshpatharva/agentic_ai:environment:production` | any job with `environment: production` |

Both credentials are already declared in Terraform. They activate after
`terraform apply` provisions the Service Principal.

**The `deploy-backend.yml`, `deploy-frontend.yml`, and terraform apply job all
use `environment: production`, which matches the `github-env-production`
credential subject.**

---

## Branch Protection (Required for CI Gate)

For CI to actually block merges, set branch protection on `main`:

1. *Settings → Branches → Add rule → Branch name pattern: `main`*
2. Enable **Require status checks to pass before merging**
3. Add required checks:
   - `Backend — lint + smoke tests`
   - `Frontend — build`
4. Enable **Require branches to be up to date before merging**

Without this, the CI workflow runs but does not block a merge.

---

## How Deploys Work

### Backend (Oryx code deploy)

`azure/webapps-deploy@v3` zips `resume-optimizer/backend/` (with
`requirements.txt` copied in) and pushes it to the App Service SCM endpoint.
Oryx then runs `pip install -r requirements.txt` on the App Service server,
including the spaCy model wheel pinned in `requirements.txt`. The startup
command (`uvicorn main:app --host 0.0.0.0 --port 8000`) is set in Terraform
and is not overridden by the workflow.

The app reads all runtime secrets (API keys, JWT secret, database URL) from
Key Vault via its System-Assigned Managed Identity at startup. CI never
injects application secrets.

### Frontend (Static Web Apps)

`Azure/static-web-apps-deploy@v1` builds the Vite app internally (runs
`npm ci && npm run build`). `VITE_API_URL` is injected at build time so the
compiled bundle points at the correct App Service URL. The deploy token is
the only secret the workflow needs.

### Terraform

Plan runs automatically on PRs that touch `infra/`. The plan output is posted
as a PR comment and saved as a 1-day artifact. Apply requires:

1. `workflow_dispatch` with `action=apply`
2. A reviewer to approve the `production` environment gate

The apply job downloads the exact plan binary from the plan job, so apply
executes precisely what the reviewer saw — no re-planning between review and
apply.

---

## First-Time Setup Order

1. `terraform apply -target=...` the state storage resources (see `backend.tf` bootstrap comment)
2. Add secrets and variables listed above to the GitHub repo
3. `terraform apply` everything else — this provisions the Service Principal with OIDC credentials
4. Create the `production` environment in GitHub with required reviewers
5. Set branch protection on `main` to require the CI status checks
6. Push to `main` — CI runs; deploys are reviewer-gated via the environment
