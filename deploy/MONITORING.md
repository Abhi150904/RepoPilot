# Production heartbeat monitor

Run `monitor_production.py` on the app VM, not the execution runner. It uses
Python's standard library and the existing Docker CLI. No backend/frontend image
rebuild is needed. It never starts/stops containers, starts the runner, claims
jobs, changes the database, or calls an LLM.

## What it checks

- The `repopilot-aws` API, database, worker, and proxy containers are running.
  API/database must also report healthy through Docker's existing health checks.
- No job has been queued longer than 20 minutes. This is an alert threshold,
  not a timeout or cancellation; a genuine large backlog can also trigger it.
- Running jobs have a recent lease/heartbeat (five-minute heartbeat threshold,
  one-minute grace on an expired lease).
- Root/workspace disks are below 85% used and have at least 2 GiB free.
- The configured Vercel homepage responds with HTTP 200, and its `/api/health`
  returns the expected service/status JSON. Redirects are not followed.

Only empty success/failure HTTP requests are sent to Healthchecks.io. No logs,
repository names, requests, tokens, or database contents are uploaded. Failed
check names are available locally in the systemd journal. Normal deallocated
runner state is not considered an outage.

## Setup

Create a Healthchecks.io Hobbyist check with a five-minute Period, five-minute
Grace Time, and an enabled email integration. Keep the ping URL private. The
script accepts only canonical `https://hc-ping.com/<UUID>` check URLs. If the
provider gives a different domain, review/update the allowlist deliberately.

After committing/pushing these files and pulling them on the app VM, preflight:

```bash
cd ~/RepoPilot
sudo python3 deploy/monitor_production.py --check-only
```

Do not enable the timer until all checks pass. Store the URL with hidden input
(it must not go into shell history, Git, screenshots, or chat):

```bash
sudo install -d -m 700 /etc/repopilot
sudo bash -c 'umask 077; read -r -s -p "Healthchecks ping URL: " url; printf "\n"; printf "%s\n" "$url" > /etc/repopilot/healthchecks-url'
sudo chmod 600 /etc/repopilot/healthchecks-url
sudo install -d -m 755 /opt/repopilot
sudo install -m 644 deploy/monitor_production.py /opt/repopilot/monitor_production.py
sudo install -m 644 deploy/repopilot-monitor.service /etc/systemd/system/repopilot-monitor.service
sudo install -m 644 deploy/repopilot-monitor.timer /etc/systemd/system/repopilot-monitor.timer
sudo systemctl daemon-reload
sudo systemctl start repopilot-monitor.service
sudo journalctl -u repopilot-monitor.service --no-pager -n 10
```

Confirm the initial heartbeat appears as Up in Healthchecks.io, then enable:

```bash
sudo systemctl enable --now repopilot-monitor.timer
systemctl list-timers repopilot-monitor.timer --no-pager
```

The timer runs after boot and every five minutes. A failed local check sends
`/fail`; missing heartbeats also produce an alert after the provider's period
and grace. A failed oneshot service does not disable its timer. Check email
integration settings and test actual email delivery rather than assuming it.

## Safe alert-delivery acceptance test

Pause only the monitor timer, not production services:

```bash
sudo systemctl stop repopilot-monitor.timer
```

Wait at least 12 minutes after the last successful heartbeat and confirm receipt
of a down email. Restore immediately, even if email has not arrived:

```bash
sudo systemctl start repopilot-monitor.service
sudo systemctl start repopilot-monitor.timer
```

Confirm recovery in the dashboard and timer status. A separate provider outage
or disabled/misrouted email integration can prevent notification delivery.

## Limits and operation

- An Up result is a point-in-time sample. A hung worker with an empty queue is
  not proven responsive by its container state alone. Old queued jobs or stale
  active heartbeats detect many, but not all, execution failures.
- HTTP requests originate on the app VM. This checks its path through Vercel,
  not every user's browser, geography, DNS, OAuth session, or GitHub operation.
- This is not an Azure spending cap, full security audit, backup, or repair
  service. It does not detect a runner left running without queued work.
  Continue to inspect Azure costs, credits, runner state, and storage growth.
- During deliberate worker-stopping tests or maintenance, pause the timer to
  avoid expected alerts, then resume it immediately afterwards.
- Root is required for the Docker socket and private heartbeat file. Never
  copy the heartbeat file or Docker socket to the untrusted execution runner.
- Service timeouts are bounded; network exceptions are redacted so a failed
  delivery cannot print the secret ping URL. Check output contains only booleans.
- Change `SITE`/container names deliberately if the deployment is renamed.
  To update, reinstall the changed files and run `daemon-reload` if units changed.

References: [Healthchecks pricing](https://healthchecks.io/pricing/),
[heartbeat monitoring](https://healthchecks.io/docs/monitoring_cron_jobs/).
