# AWS + Vercel deployment preparation

This is configuration for a two-host deployment, not evidence of a live or
security-audited public service. Do not provision resources until their regional
cost estimate and credit eligibility have been reviewed. Polar sandbox and PyPI
follow deployment; neither is removed from the roadmap.

## Boundaries

- Vercel hosts Next.js at its stable production `*.vercel.app` hostname.
- App EC2 hosts Caddy, one API process, PostgreSQL and the trusted workflow worker.
  API and worker share workspaces and the budget ledger locally. Approval and
  publication require these files, so they must not move independently.
- Execution EC2 hosts only Docker, SSH and prepared test images. The worker uses
  Docker over SSH to its private IP. Neither app container mounts a Docker socket.
- Each test gets a bounded archive, excluding `.git`, `.env*`, private-key files,
  dependency directories and links. No shared host directory is mounted. The test
  container has no app environment, networking, credentials or Docker socket.
- Remote tests use UID 65534, read-only root, bounded tmpfs workspace and temp,
  CPU/memory/PID limits, dropped capabilities and no-new-privileges. Captured
  output is bounded while draining, not just truncated after unlimited capture.
- Timeout cleanup removes the remote container. Run `runner_reaper.py` every
  minute independently on the execution VM to remove labelled containers older
  than ten minutes when the worker crashes or loses SSH connectivity.

The SSH key grants Docker administrator access to the execution machine. Do not
forward an SSH agent or reuse your personal/admin key. A container escape can
compromise that execution host: no IAM role, cloud keys, app secrets, database
access or unrelated workloads belong there. Reject traffic from the runner to
the app at the app security group; deny runner access to metadata and private
networks with host-level egress controls, including IPv6. Docker containers must
remain network-disabled. Disable EC2 instance metadata on the execution host.
Do not expose Docker TCP ports 2375/2376. Retain Docker's default seccomp policy.

## Resource proposal to price before creating

Use Linux x86-64 EC2, on-demand rather than Spot for predictable demos. Start by
pricing an app host with 2 vCPU / 4 GiB and an execution host with 2 vCPU / 4 GiB,
with one workflow worker. These are initial sizing candidates, not verified
capacity. Include both EBS disks, public IPv4 addresses, traffic and backups.
Do not add RDS, ALB, NAT Gateway or Kubernetes just for this demo. Burstable CPU
surplus charges must be included or avoided through Standard credit mode.
Prices and quotas vary by region and subscription; do not assume micro instances
can run the full stack. Credit expiry does not imply the stack lasts that long.

Put hosts in the same VPC. Allow app inbound 80/443 publicly and admin SSH only
from your IP. Allow runner SSH only from the app security group (and temporarily
your admin IP if needed). Database has no host-published port. Direct VPC routes
are used for SSH; a runner without a public address needs a deliberate outbound
image-build/update plan, not an accidentally billable NAT Gateway.

## Vercel and login

Import the repo with root directory `frontend`. Set production variables:

```dotenv
NEXT_PUBLIC_REPOPILOT_API_URL=/api
REPOPILOT_API_ORIGIN=https://repopilot.duckdns.org
```

The server-side Next.js rewrite forwards `/api/*` to the API without the prefix.
Use the stable Vercel production URL, not per-commit preview URLs, for OAuth.
The GitHub callback is `https://YOUR-PROJECT.vercel.app/api/auth/github/callback`.
The callback and login both pass through Vercel so cookies remain on one origin;
do not send the browser straight to Duck DNS for login. Confirm Set-Cookie,
redirects, CSRF Origin checks and authenticated polling in a live browser before
sharing. Avoid caching authenticated API responses at a CDN.

## App host configuration

Create untracked `.env.aws` on the server, mode 600. Copy the environment keys
listed in STAGING.md, with these differences (never upload a local `.env`):

```dotenv
API_DOMAIN=repopilot.duckdns.org
REPOPILOT_DEPLOYMENT_ENVIRONMENT=production
REPOPILOT_HOSTED_MODE=true
REPOPILOT_INLINE_RUN_EXECUTION=false
REPOPILOT_PUBLIC_BASE_URL=https://YOUR-PROJECT.vercel.app
REPOPILOT_CORS_ORIGINS=https://YOUR-PROJECT.vercel.app
GITHUB_OAUTH_CALLBACK_URL=https://YOUR-PROJECT.vercel.app/api/auth/github/callback
REPOPILOT_SANDBOX_DOCKER_HOST=ssh://sandbox@sandbox-runner
REPOPILOT_SANDBOX_IMAGE=repopilot-sandbox:aws
```

Production configuration requires hosted mode, durable database, OAuth/App
credentials, HTTPS and remote sandbox configuration. Production does not use the
staging GitHub-ID allowlist. Do not switch existing staging to production until
the execution host, firewall and acceptance checks are verified.

Install the dedicated worker SSH key, config and independently verified host key
under `/etc/repopilot/runner-ssh/` on the app host. Rename runner-ssh.config to
`config`, replace the private IP, store the private key as `runner_key`, and create
`known_hosts`. Verify the runner host fingerprint through your trusted admin
connection before trusting it; do not blindly accept ssh-keyscan output. Use
permissions 700 for the directory and 600 for key/config. Never commit these files.

On the execution host, install Docker and Python 3, create the dedicated `sandbox`
SSH user with Docker access, and install only that worker's public key. Build
`deploy/Dockerfile.sandbox` as `repopilot-sandbox:aws` on that host, not the app
host. Extend the image with pinned repository dependencies before running tests.
Remote images must contain Python 3.12+ for safe archive extraction; Node projects
also need Python and prepared Node dependencies. Runtime pulls and dependency
downloads are disabled. `.env*` fixtures and symlink-dependent repositories are
not supported by this transfer policy and require explicit design, not fallback
to local execution. Test-generated files stay remote and are discarded.

Install runner_reaper.py at `/opt/repopilot/runner_reaper.py` on the runner and
schedule `python3 /opt/repopilot/runner_reaper.py` every minute via a root systemd
timer or cron. Verify an orphan is removed before enabling public runs.

On app host, after secret setup and DNS:

```sh
docker compose --env-file .env.aws -f deploy/compose.aws.yml config --quiet
docker compose --env-file .env.aws -f deploy/compose.aws.yml up -d --build
docker compose --env-file .env.aws -f deploy/compose.aws.yml ps
```

Point Duck DNS at the app host public IP. Caddy obtains HTTPS after DNS and
firewall validation. No frontend container is deployed on AWS in this topology.

## Release gates

Before opening access, verify a real remote test, timeout cleanup, orphan reaper,
no secrets in archives, no app/database/metadata access from the runner, disk
pressure and host reboot recovery. Verify OAuth, cross-user access denial,
quota/budget enforcement, approval binding and exactly one intended PR. Add
monitoring for queue stalls, runner cleanup failures, disk usage and budget.
Use mock provider for failure tests. Back up PostgreSQL and app data/budget ledger
and test restore. API sessions remain in-memory: use one API replica; restart
signs users out. Live cloud/OAuth/rewrite verification and operational isolation
are required; unit tests alone are not approval for arbitrary hostile execution.

Keep real runs limited while Polar sandbox is added. Fake purchases must not
override owner-enforced spending and abuse limits. Public payment demonstration
is separate from permission to consume unlimited paid API calls.

References: https://docs.docker.com/engine/security/protect-access/
and https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites

## Local verification (2026-10-17)

- Backend regression suite: 329 passed, 4 opt-in tests skipped. Automatic local
  `.env` loading was disabled and Git parent discovery bounded for isolation.
- Frontend: 58 tests passed, including HTTPS proxy validation; TypeScript passed.
- AWS Compose configuration validated with placeholders and no secret env file.
- Updated backend image built; SSH, Docker CLI and sandbox imports smoke-tested
  with networking disabled and no credentials mounted.
- Two opt-in real Docker tests passed using the local engine: archive extraction,
  non-root execution, secret exclusion and timeout cleanup. No labelled test
  containers remained afterward. This validates container behavior, not SSH/VPC
  isolation. Remote SSH and live Vercel cookie forwarding remain release gates.
