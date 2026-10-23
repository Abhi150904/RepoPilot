<div align="center">

# RepoPilot

### Ship fixes, not tickets.

Turn GitHub issues into repository-aware changes, tested code, and reviewable pull requests.
Let the agent do the groundwork. Keep the final decision yours.

**[Open RepoPilot](https://repo-pilot-sigma.vercel.app)** &nbsp; | &nbsp; **[See the Workflow](#the-workflow)** &nbsp; | &nbsp; **[Run Locally](#run-locally)**

Autonomous engineering. Human-controlled shipping.

</div>

---

## Your Issue. A Clear Path to a Pull Request.

An issue is the starting point, not the whole context. RepoPilot explores the repository, finds relevant code, builds an implementation plan, writes changes, and runs tests in an isolated environment. You get the diff, test evidence, and review before deciding whether to publish a pull request.

No blind handoff. No automatic merge. An engineering workflow you can inspect from start to finish.

| From the backlog to review | What you get |
| --- | --- |
| **Context before code** | Repository exploration and hybrid retrieval surface relevant files and code chunks. |
| **A plan you can follow** | Structured issue analysis and implementation steps connect the problem to the proposed change. |
| **Changes with evidence** | Generated diffs, isolated test output, and bounded repair attempts stay attached to the run. |
| **You control publication** | Inspect, approve or reject, then publish a pull request. Approval is required before publication. |
| **Progress that survives a refresh** | Durable jobs, run timelines, saved artifacts, and worker recovery keep execution separate from the browser. |
| **Limits built in** | Account allowances, concurrency limits, and AI spending guards put boundaries around execution. |

## The Workflow

**Issue -> Analyze -> Retrieve -> Plan -> Code -> Test -> Review -> Your approval -> Pull request**

1. **Connect your repository.** Sign in with GitHub and install the GitHub App on the repositories you choose.
2. **Start with an issue.** Launch an AI run from the Command Center and follow its progress in Runs.
3. **Inspect the work.** Review the plan, changed files, test results, and agent review. When tests fail, a bounded repair loop can attempt a correction.
4. **Decide what ships.** Approve or reject the proposed change. Publish approved work as a GitHub pull request; merging remains your decision.

## One Workspace, From Launch to Review

| Workspace | Purpose |
| --- | --- |
| **Command Center** | Start a real AI run; see your free allowance and purchased run credits. |
| **Runs** | Follow execution, inspect artifacts and failures, and review changes before publication. |
| **Repositories** | Browse repositories available through your GitHub installation. |
| **Billing** | Buy run credits and inspect your balance, purchases, and activity. |
| **Settings** | Inspect account and application configuration. |

### Try the Workflow on Your Terms

Hosted accounts receive **two lifetime introductory AI runs per GitHub account**, subject to capacity and spending limits. These run the actual engineering workflow. Existing owned runs count toward the allowance; it does not reset after a deployment.

After the two introductory runs, continue with run credits. A **$5 sandbox checkout grants five credits**. Each additional real AI run uses one credit. Free attempts are always used before purchased credits; reviewing or reopening a run never costs another credit.

**Payments are test-only; no real money is collected. The AI runs are real** and use the application's configured model provider and execution environment. All concurrency, daily admission, and AI spending limits remain in effect. Billing displays financial activity; execution belongs in the Command Center.

> RepoPilot is an early-access engineering application. The workflow has been exercised on controlled repositories, not certified for arbitrary projects or unrestricted multi-tenant execution. This README describes the current source; the hosted deployment may lag unreleased changes.

## Built Around Trust Boundaries

- **Human approval:** generated code does not become a published PR without approval.
- **Account ownership:** hosted runs, purchases, and balances belong to the signed-in GitHub account.
- **Isolated execution:** repository tests run in restricted Docker containers, with a separate execution host required for production.
- **Restricted containers:** non-root execution, disabled networking, a read-only root filesystem, and resource, output, and time limits constrain test execution. Workspace archives exclude sensitive files and Git configuration.
- **Cost-aware AI:** per-run and shared-ledger spending guards reserve estimated costs before provider requests; account limits also restrict admission.
- **Verified payment events:** signed webhooks, order validation, and replay-safe ledger entries determine credits, not checkout redirects or browser state.

These are engineering guardrails, not a security audit or a guarantee that all untrusted code is safe. Dependency-heavy repositories need an appropriately prepared sandbox image; test containers cannot download dependencies from the network.

## Under the Hood

```text
Browser / Next.js frontend (Vercel)
                 |
            HTTPS API
                 |
       FastAPI + GitHub authentication
          |                    |
   PostgreSQL             Polar sandbox
   jobs / artifacts       signed webhooks
   usage / ledger
          |
   Dedicated workflow worker
          |
   LangGraph + repository retrieval + model provider
          |
   SSH -> isolated Docker runner (Azure, on demand)
          |
   Diff + tests + review -> human approval -> GitHub PR
```

| Layer | Technology |
| --- | --- |
| Web application | Next.js, React, TypeScript, Tailwind CSS, Radix UI, Lucide |
| API and workflows | Python 3.11+, FastAPI, LangGraph, Pydantic |
| Persistence | SQLAlchemy, Alembic, PostgreSQL; SQLite for local tests |
| Repository context | Keyword search, BM25, deterministic local vector embeddings, rank fusion, and a reranker interface |
| Model providers | OpenAI Responses API with structured outputs; deterministic mock provider for development |
| Execution | Docker sandbox, dedicated worker, durable claims and heartbeats |
| Hosted infrastructure | Vercel frontend, Azure app and runner VMs, Caddy HTTPS proxy |
| Payments and monitoring | Polar sandbox; scheduled production checks and Healthchecks heartbeats |

The app host keeps trusted services online while the isolated Azure runner can start on demand and deallocate when idle. Free and credit-funded runs use the same engineering workflow and approval gates.

## Run Locally

Use **Python 3.11+**, **Node.js 20+**, and Git. Docker is needed for sandboxed test execution. The default model provider is `mock`, so the basic local workflow needs no paid AI key. GitHub-backed operations require appropriate repository access.

### Backend

```sh
git clone https://github.com/Abhi150904/RepoPilot.git
cd RepoPilot
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate` on macOS/Linux. Then:

```sh
python -m pip install -e ".[dev]"
repopilot-api-dev
```

The API runs at `http://127.0.0.1:8000`; interactive API documentation is at `http://127.0.0.1:8000/docs`.

### Frontend

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The frontend uses `http://localhost:8000` by default. Override `NEXT_PUBLIC_REPOPILOT_API_URL` only when using another API origin or a configured same-origin proxy. Hosted sign-in and sandbox billing require the additional configuration below.

### CLI

```sh
repopilot run --issue-text "Login endpoint returns 500 when email is missing"
repopilot run --repo owner/name --issue 123
repopilot run --repo owner/name --issue 123 --apply --test
repopilot run --help
```

The CLI also supports approval/publication controls and JSON output. Private evaluations are available through `repopilot eval retrieval` and `repopilot eval workflow`; they are not exposed as public web pages or evaluation API endpoints.

## Configuration and Operations

<details>
<summary><strong>Model configuration and spending limits</strong></summary>

Set private configuration in the root `.env` or your deployment's secret environment. Never commit tokens or environment files. To opt into real OpenAI calls:

```dotenv
REPO_PILOT_LLM_PROVIDER=openai
REPO_PILOT_LLM_MODEL=gpt-5.4-mini
OPENAI_API_KEY=<your private API key>
REPO_PILOT_LLM_MAX_OUTPUT_TOKENS=8192
REPO_PILOT_LLM_MAX_PROMPT_CHARS=60000
REPO_PILOT_LLM_MAX_RETRIES=2
REPOPILOT_LLM_BUDGET_USD=5
REPOPILOT_LLM_RUN_BUDGET_USD=0.50
REPOPILOT_LLM_BUDGET_PATH=.repopilot/openai-budget.sqlite
REPO_PILOT_DEFAULT_TEST_COMMAND=python -m pytest
```

Only `mock` and `openai` are supported. Per-role model overrides are available; the spending guard rejects models without a verified entry in `backend/app/core/pricing.py`.

Before each provider attempt, the ledger reserves estimated input cost plus maximum output cost, then replaces the reservation with reported usage. Reasoning tokens count toward output usage. Timeouts and missing usage retain their reservations; unknown cost is never silently treated as zero. Oversized prompts stop before a paid request rather than silently truncating whole-file replacement context.

The default $5 shared-ledger and $0.50 per-run budgets are **RepoPilot guards, not provider billing caps**. They cannot see other applications or machines, and deleting the ledger resets its history. Use one persistent absolute ledger path across workers, outside source repositories. Unknown network outcomes may conservatively consume the local budget even when no charge occurred.

</details>

<details>
<summary><strong>GitHub access, hosted usage, and account limits</strong></summary>

Local CLI use can supply `GITHUB_TOKEN` for private repositories and publishing permissions. Hosted mode instead requires GitHub OAuth and GitHub App credentials, a durable database, an HTTPS frontend/callback, explicit CORS origins, and a separate worker. Do not configure a personal GitHub token in hosted mode.

Hosted real runs have two lifetime introductory attempts per immutable GitHub user ID. Accepted jobs atomically reserve an attempt; the worker consumes it just before workflow invocation, after workflow construction and credential setup. Setup failures and stale claims recovered before invocation release it. Failures or interruptions after invocation still count. A crash immediately after the persisted execution marker can count even before the first provider request reaches the provider. Runner readiness failures leave the queued job's attempt reserved, not consumed.

Repairs within a run, reviewing, rejecting, publishing, refreshing, and replaying the same accepted idempotent request do not take an extra attempt. Default additional limits are one queued/running job per user and five admissions in a rolling 24-hour window, configured with `REPOPILOT_USER_MAX_ACTIVE_RUNS` and `REPOPILOT_USER_MAX_DAILY_RUNS`. These hosted admission limits do not apply to the local CLI; model spending guards still do.

After the introductory allowance is used or reserved, admission atomically reserves one purchased credit in the same database transaction that creates the queued run. Failed admission or an idempotent replay cannot debit twice. Setup failure or stale-worker recovery before execution releases the credit once; failures after execution starts still count. A refund that makes the balance negative prevents an unstarted credit-funded run from beginning. Runner boot failures leave its queued reservation in place.

`GET /usage` reports the account's introductory usage and available `run_credits`. `GET /billing` reports `credit_balance` and financial history. There are no simulation endpoints or fixed example runs. Sandbox purchases unlock actual AI execution at the operator's expense; keep the persistent AI budget ledger and account limits enabled.

</details>

<details>
<summary><strong>Polar sandbox setup, credits, and refunds</strong></summary>

Billing is disabled by default. The integration accepts **sandbox mode only**, with fixed sandbox API and checkout hosts. No live merchant onboarding is needed.

1. Create an organization at [Polar sandbox](https://sandbox.polar.sh).
2. Create a public one-time fixed-price product, `RepoPilot Run Credits`, at USD 5.00. Do not add subscriptions, trials, discounts, or variable pricing. An existing product can be renamed without replacing its ID.
3. Record the product and organization IDs. Create an organization token with `checkouts:write` only.
4. Add an HTTPS webhook at your API origin's `/billing/webhook` path. The hosted endpoint is `https://repopilot.duckdns.org/billing/webhook`. Select **Raw / JSON**, API version **2026-04**, and events **`order.paid`** and **`order.refunded`**. This matches the backend's explicit checkout API version.
5. Put the credentials directly into the app host's private environment:

```dotenv
REPOPILOT_BILLING_ENABLED=true
REPOPILOT_POLAR_SERVER=sandbox
REPOPILOT_POLAR_ACCESS_TOKEN=<sandbox organization token>
REPOPILOT_POLAR_WEBHOOK_SECRET=<endpoint signing secret>
REPOPILOT_POLAR_PRODUCT_ID=<product ID>
REPOPILOT_POLAR_ORGANIZATION_ID=<organization ID>
REPOPILOT_PUBLIC_BASE_URL=https://repo-pilot-sigma.vercel.app
```

Keep the signing secret exactly as provided; do not encode it yourself. Both current Standard Webhooks secrets and legacy Polar HMAC secrets require valid signatures and recent timestamps. Never put these secrets in browser code or `NEXT_PUBLIC_` variables. Billing also requires the database and complete checkout configuration.

Only a verified `order.paid` event matching the expected checkout, customer, organization, product, currency, and amount grants five credits. A success redirect, unrelated event, canceled checkout, or provider error grants nothing. Order identifiers and run idempotency prevent duplicate grants and charges.

Any positive refund, including a partial refund, revokes the full five-credit pack once. Previously spent credits can leave a negative balance, which blocks further spending. A refund received before payment confirmation prevents a late grant. Existing purchases and ledger balances survive migration.

The UI shows up to twenty recent purchases and ledger entries. Checkout return polls for up to a minute; use Refresh if confirmation is delayed. Failed checkout creation is recorded as failed; abandoned intents remain pending and are never treated as paid. Up to five pending checkout creations per account per UTC day are allowed. Automatic expiry reconciliation is not implemented.

For missing credits, inspect webhook delivery and redeliver after fixing configuration. Never edit balances based on a success-page screenshot. Checkout return URLs can contain customer session tokens; the app removes that parameter, but do not share the original URL or secrets in screenshots.

</details>

<details>
<summary><strong>Hosted deployment and release verification</strong></summary>

The deployed topology uses Vercel and Azure. Existing `.env.aws` and `compose.aws.yml` names are retained for compatibility; those filenames do not imply that the current host is AWS.

Infrastructure preparation, network isolation, rollback, and identity requirements remain in [Azure runner operations](deploy/AZURE.md), the [execution-host deployment guide](deploy/AWS.md), and [restricted staging](deploy/STAGING.md). Read these before provisioning; Compose files alone do not provision or secure cloud resources.

For an existing installation, review and merge the complete change with passing checks. On the **app VM**, schedule a maintenance window with no queued/running real workflows and take a database backup. Never delete database volumes.

```sh
cd ~/RepoPilot
git switch main
git pull --ff-only origin main
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml build migrate api worker
```

Stop if the build fails. Then stop the API and worker together before migrating:

```sh
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml stop api worker
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml run --rm migrate
```

If migration fails, keep these services stopped until diagnosed. Do not restart mixed code versions. On success:

```sh
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml up -d api worker
```

Allow container health checks to run, then verify:

```sh
sudo python3 deploy/monitor_production.py --check-only
```

All checks must pass. Confirm Vercel Production is Ready for the matching merged commit. Migration `20261023_0008` supplies the allowance state; existing owned runs are backfilled instead of receiving a fresh allowance. This update reuses that state and the existing billing ledger, so installations already on `0008` need no new schema migration. Existing balances, purchases, artifacts, and approvals are preserved. Legacy simulation records remain archived in the database but are no longer exposed or executable. No runner rebuild, new ports, or replacement Polar product is needed. You can rename the existing Polar product to `RepoPilot Run Credits` without changing its ID or price.

Verify the release end to end:

- Billing has no execution button; Command Center shows free runs and purchased run credits without a simulation mode.
- Existing balances remain unchanged, and historical owned runs count toward introductory usage.
- Free runs leave the credit balance unchanged. After both are used, an accepted real run reserves exactly one credit. Replaying the same request, refreshing, or reopening spends nothing extra.
- Before execution, setup failure releases the credit; after execution begins, failure still counts. Credits cannot bypass daily, concurrency, or model spending limits.
- A completed sandbox purchase grants five credits only after the signed event. Event redelivery adds nothing; cancellation adds nothing.
- A refund revokes the pack once, including on redelivery. Negative balances block new credit-funded runs and unstarted paid reservations until resolved.
- A second GitHub account cannot access the first account's runs, purchases, or balance.
- Checkout session tokens are removed from the returned address, and production checks and the scheduled monitor remain healthy.

Local database tests use SQLite. Also verify webhook redelivery, account isolation, and concurrent spending against a disposable PostgreSQL database before opening the integration to untrusted traffic. Passing local tests or merging code alone does not verify a hosted release.

The production monitor covers the API, database, worker, proxy, queue/leases, disk space, website, and public API. The systemd timer runs every five minutes and can send Healthchecks heartbeats. Keep that heartbeat URL private.

</details>

## Development Checks

From the repository root, with the Python environment active:

```sh
python -m pytest backend/tests -q
```

From `frontend`:

```sh
npm test
npm run typecheck
npm run build
```

The automated suites exercise workflows, retrieval, authentication and ownership, budgets, durable execution, introductory allowances, billing, migrations, and frontend behavior. Payment tests use fake provider responses; they do not replace verification of actual sandbox webhook delivery. Routine tests need no paid model requests.

## Explore the Code

```text
backend/app/          API, authentication, agents, workflow graph, retrieval, services
backend/migrations/  Versioned database migrations
backend/tests/       Backend, persistence, security, and workflow tests
frontend/            Web application, shared components, API client, and UI tests
deploy/              Containers, cloud operations, production monitoring
```

---

**Less time moving tickets. More time reviewing work that moves them forward.**

[Launch RepoPilot](https://repo-pilot-sigma.vercel.app) | [Browse the Source](https://github.com/Abhi150904/RepoPilot)
