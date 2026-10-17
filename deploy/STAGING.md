# Phase 20: restricted staging

This is a deployment preparation, not an already provisioned service. Use a
dedicated Linux VM with Docker Engine and Compose, a domain pointing at its IP,
and enough RAM for the frontend build and one sandbox (start with 4 GB; measure
your repositories before choosing a long-term size). Provider and billing remain
the owner's decision. Never run this on a machine holding unrelated production
secrets.

## Architecture and boundaries

Caddy terminates HTTPS on one domain. `/api/*` proxies to FastAPI with the prefix
removed; all other paths go to Next.js. Keeping frontend and API on the same
origin avoids third-party-cookie dependencies. Only ports 80 and 443 are exposed
by Compose. Restrict SSH separately in the VM firewall; never expose PostgreSQL,
the Docker API, the API container, or the frontend port directly.

The API and worker share `/opt/repopilot/data` at exactly the same host and
container path. This is required because sandbox bind mounts are resolved by the
host Docker daemon, not by the worker container. This directory contains mutable
repository workspaces and the persistent OpenAI budget ledger.

Use exactly one API process/replica. Sessions and OAuth state are currently
in memory: restarting that process signs users out. Database-backed encrypted
sessions are future work before horizontal scaling. Worker restarts do not erase
durable jobs; stale leases are recovered periodically. Lost database connections
are retried at 1, 2, 4, 8, 16, then 30-second intervals. There is no automatic
replay of a workflow after an uncertain database commit; inspect its recorded
state before creating a replacement run. Single-shot worker commands still exit
on failure so scripts can detect an error.

The worker alone mounts the host Docker socket, which grants powerful host
access. This is a trusted-tester staging setup, not a hostile multi-tenant sandbox.
Test containers receive no API environment or Docker socket, have networking
disabled, limited CPU/RAM/processes, dropped capabilities, and no-new-privileges.
Git operations and the worker itself are not a security boundary against arbitrary
malicious repositories. A stronger execution boundary and an audit are required
before an unrestricted public launch.

## Configure

On the VM, clone the intended branch and create `/opt/repopilot/data`. Create an
untracked `.env.staging` at the repository root with mode 600. Do not reuse or
upload your development `.env`. Fill these values through the server's secret
management process; none should be committed:

```dotenv
STAGING_DOMAIN=staging.your-domain.example
POSTGRES_PASSWORD=REPLACE_WITH_LONG_RANDOM_URL_SAFE_PASSWORD
REPOPILOT_DATABASE_URL=postgresql+psycopg://repopilot:REPLACE_WITH_THE_SAME_PASSWORD@database:5432/repopilot
REPOPILOT_DEPLOYMENT_ENVIRONMENT=staging
REPOPILOT_HOSTED_MODE=true
REPOPILOT_INLINE_RUN_EXECUTION=false
REPOPILOT_PUBLIC_BASE_URL=https://staging.your-domain.example
REPOPILOT_CORS_ORIGINS=https://staging.your-domain.example
REPOPILOT_STAGING_GITHUB_USER_IDS=REPLACE_WITH_YOUR_NUMERIC_GITHUB_ID
GITHUB_CLIENT_ID=REPLACE
GITHUB_CLIENT_SECRET=REPLACE
GITHUB_APP_ID=REPLACE
GITHUB_APP_NAME=REPLACE_WITH_ACTUAL_APP_URL_SLUG
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nREPLACE\n-----END RSA PRIVATE KEY-----"
GITHUB_OAUTH_CALLBACK_URL=https://staging.your-domain.example/api/auth/github/callback
REPOPILOT_WORKSPACE_ROOT=/opt/repopilot/data/workspaces
REPO_PILOT_LLM_PROVIDER=openai
REPO_PILOT_LLM_MODEL=gpt-5.4-mini
OPENAI_API_KEY=REPLACE
REPOPILOT_LLM_BUDGET_USD=5
REPOPILOT_LLM_RUN_BUDGET_USD=0.50
REPOPILOT_LLM_BUDGET_PATH=/opt/repopilot/data/openai-budget.sqlite
REPOPILOT_USER_MAX_ACTIVE_RUNS=1
REPOPILOT_USER_MAX_DAILY_RUNS=5
REPOPILOT_SANDBOX_IMAGE=repopilot-sandbox:staging
GIT_AUTHOR_NAME=RepoPilot
GIT_AUTHOR_EMAIL=REPLACE_WITH_VALID_BOT_EMAIL
GIT_COMMITTER_NAME=RepoPilot
GIT_COMMITTER_EMAIL=REPLACE_WITH_VALID_BOT_EMAIL
```

The allowlist uses immutable numeric IDs, not login names. Separate multiple IDs
with commas. Unapproved users cannot receive a session. Existing sessions are
rechecked on protected API requests after an allowlist change. An empty allowlist,
non-hosted mode, insecure frontend/callback URLs, or inline execution prevents the
staging API from starting. Keep `GITHUB_TOKEN` unset: hosted runs use scoped App
installation tokens.

Use a separate staging GitHub App/OAuth registration so local development keeps
its own callback. Set the callback and App setup/return URLs to the public staging
origin (the callback includes `/api`). Install the App only on test repositories.
Check private-key formatting using `repopilot config validate`; never print or
paste private keys in logs or issue reports.

## Build and start

From the repository root on the VM:

```sh
docker build -f deploy/Dockerfile.sandbox -t repopilot-sandbox:staging .
docker compose --env-file .env.staging -f deploy/compose.staging.yml config --quiet
docker compose --env-file .env.staging -f deploy/compose.staging.yml up -d --build
docker compose --env-file .env.staging -f deploy/compose.staging.yml ps
docker compose --env-file .env.staging -f deploy/compose.staging.yml logs --tail=100 api worker proxy
```

The one-shot migration service must succeed before the API and worker start.
The frontend API URL is baked into its build; rebuild it if the domain changes.
The proxy obtains a TLS certificate after DNS and firewall settings are correct.
No development reloaders run in this stack.

The sample sandbox image contains Python and pytest only. Build a separate image
with your test repository's pinned dependencies before verifying it; select it
using `REPOPILOT_SANDBOX_IMAGE`. Node projects need a Node image and prepared
dependencies too. Dependencies are not fetched in the network-disabled test
container. Do not work around missing dependencies by selecting local execution
in staging: hosted requests force Docker and never fall back to host npm.

The public `/health` endpoint checks process liveness; `/ready` currently checks
configuration, not live database/worker availability. Check migration completion,
database container health, and actual worker progress separately.

## Acceptance checks before sharing the staging URL

### Local image verification (2026-10-17)

All three Dockerfiles built successfully with Docker Desktop's Linux engine.
The production frontend served `/`, `/app`, `/runs`, and `/settings` with HTTP
200, and `/evaluations` with 404. The backend imported and served its health
endpoint without credentials or external networking. The restricted pytest image
and packaged Docker CLI executed successfully.

All Alembic migrations applied to a disposable PostgreSQL 16 database. Persistent
run creation, per-user quota admission (including PostgreSQL advisory locks), and
idempotent replay passed there. A mock-provider worker survived test-database
restarts without a container restart and reconnected afterward. No paid provider
calls, live GitHub OAuth/PR actions, or public TLS deployment were exercised.

The initial Next.js/PostCSS production advisories were addressed with Next.js
15.5.28, React/React DOM 19.3.1, and PostCSS 8.5.30 (also enforced for nested
copies). `npm audit --omit=dev` reports zero production vulnerabilities at this
verification point. All 53 frontend tests and TypeScript checks passed.
The patched Docker image also built and served every public page plus both
dynamic run routes, with evaluations returning 404. Runtime checks confirmed that
Vitest, ESLint, and TypeScript are absent from the pruned image.

The full development dependency audit still reports 15 advisories (including
two critical reports in the Vitest dependency tree). These require a separate
development-toolchain update; keep dev/test servers private. The production image
prunes development dependencies after building. Do not use a blind
`npm audit fix --force` as the release procedure, and rerun audits before release.

1. Approved GitHub ID can sign in; an unapproved account gets 403 and no session.
2. Repositories show only those authorized for the signed-in account.
3. A test issue queues, is claimed, and completes in the worker; pages update
   without reload. Review diffs and evidence before approving.
4. Publication creates only the intended test branch/PR. Once published, approve
   and reject are unavailable and backend review mutations return 409.
5. A second user cannot read or mutate another user's run. CSRF checks reject
   forged mutations. Evaluations and their API routes return 404.
6. Confirm per-user active/daily limits and persisted budget limits. Use mock
   provider for deliberate failure-path testing; real runs spend API credits.
7. Interrupt database connectivity in a disposable test environment. The worker
   backs off and resumes queue polling after recovery without publishing twice.
8. Restart services: API sessions expire as documented, and jobs/workspaces/budget
   ledger persist. Inspect interrupted jobs rather than automatically rerunning.

## Operations and rollback

Back up both the PostgreSQL database and `/opt/repopilot/data`, including the
SQLite budget ledger. Stop the worker while taking a consistent ledger/workspace
snapshot, or use SQLite's backup API. Protect these backups as credentials and
private source code can be sensitive. Test restore on a separate VM.

For application rollback, deploy a previously tested Git revision and rebuild.
Do not blindly downgrade database migrations or delete volumes. Never use
`docker compose down -v` unless intentionally destroying the staging database.
Keep staging restricted until live acceptance checks have been completed.

Payments, PyPI publication, public signup, multi-replica sessions, and managed
cloud provisioning are not part of this staging setup.
