# Azure runner on demand + Vercel

The app VM and trusted workflow worker remain online. Only the isolated Docker
execution VM starts on demand. This is code/configuration, not a provisioned or
live-verified runner. The existing `.env.aws`, `compose.aws.yml`, and sandbox image
tag are retained so the already-running Azure API does not need a filename migration.
The isolation and acceptance gates in AWS.md still apply, translated to Azure NSGs.

## Credit budget gate before creating anything

Read the actual remaining balance/currency and expiry in Azure Education. Keep
the student subscription spending limit on; do not upgrade to pay-as-you-go.
This code does not read your account balance or guarantee credit eligibility.

Public Central India USD consumption rates checked on 2026-10-18:

| Resource | Rate |
| --- | ---: |
| Linux Standard_B2als_v2 (not Spot/Windows) | $0.0246/hour |
| E4 32 GiB Standard SSD LRS OS disk | $2.64/month each |
| Standard static public IPv4 | $0.005/hour each |

At 730 hours/month the app compute is $17.958. Two OS disks are $5.28.
One public IPv4 is $3.65; two are $7.30. That is **$26.888/month with one IP**
or **$30.538/month with two**, before runner compute, disk transactions, diagnostics,
traffic, taxes/offer differences and any other resources in the subscription.
Twenty runner hours/month add $0.492/month. Include boot, idle grace and retries
in those hours, not just test duration. Retaining a runner public IP costs money
even while deallocated. A private-only runner needs an explicit bootstrap/update
plan; do not accidentally add a paid NAT Gateway just to save one IP.

With a hypothetical $100 balance, four months is NOT covered even at the one-IP
base ($107.55 before runner/other usage). Three months with two IPs and 20 runner
hours/month is about $93.09 before extras, leaving little margin. Do not promise
recruiter availability for four months on that assumption. A lower fixed-cost app
host, additional eligible credits, or shorter availability needs a separate decision.
Azure credits do not cover OpenAI API spending.

The read-only calculator fetches current public rates, not account credentials:

```sh
python3 deploy/estimate_azure_cost.py --remaining-usd 100 --months 4 --public-ips 2 --runner-hours-per-month 20 --other-monthly-usd 3
```

Replace 100 with a verified USD balance, or convert your displayed currency using
the subscription's actual billing terms. The allowance of 3 is illustrative, not
a quote. The tool reports headroom and a 15% reserve check, not a hard cost ceiling.
Review Cost Analysis after initial use; budget alerts are notifications, not caps.

## Provisioning prerequisites (do not skip)

- Create `repopilot-runner` in Central India in the same VNet, preferably its own
  subnet, with a static private NIC address so deallocation does not break SSH.
  Use Ubuntu x64, no managed identity, no secrets, no app/data disks, no Docker TCP.
- Allow SSH to the runner only from app private IP `172.16.0.4`, with any temporary
  admin-IP rule removed after bootstrap. No HTTP/HTTPS inbound needed on the runner.
- Explicitly deny the runner subnet access to the app subnet at the app NSG.
  Azure's default AllowVNetInBound is not isolation. Preserve required platform
  traffic according to Azure documentation. Test denies, not just rule presence.
- Block runner metadata/private-network egress, including IPv6, while retaining
  necessary SSH replies. Keep test containers network-disabled. Do not enable a
  managed identity on this machine. A Docker escape must not reach the app/DB/IMDS.
- Install Docker, the dedicated `sandbox` SSH user, a prebuilt Python 3.12+ image
  tagged `repopilot-sandbox:aws` with the demo repo dependencies, and the independent
  minute-by-minute runner reaper from AWS.md. Docker must start at VM boot.
- Install the dedicated worker key and independently verified host key under
  `/etc/repopilot/runner-ssh` on the app VM. Never reuse the admin private key.
  Set the runner's static private IP in `config`. Verify Docker-over-SSH manually.

## App identity and permissions

Enable **system-assigned managed identity on the app VM only**. It is a VM-wide
trust capability, not a per-container secret boundary. API/worker host compromise
can reach it. Never place untrusted repository execution on the app host.

Use `azure-runner-role.json` as a custom-role template: replace the subscription
ID in a private working copy, then create the role using Azure IAM/Cloud Shell.
Assign it to the app VM identity **at the runner VM resource scope only**, NOT
the subscription, resource group, app VM, or Owner/Contributor scope. Its only
permissions are VM read/instanceView, start and deallocate. No run-command, role
assignment, VM write/delete or secret access is granted. Verify the identity cannot
control the app VM. Defining a role at the resource group is not permission to
assign its access at that broad scope.

Worker containers must be able to reach the fixed Azure IMDS identity endpoint.
The controller uses `Metadata: true`, no HTTP proxy or redirects, short HTTP
timeouts, a cached token, and the fixed management.azure.com origin. It does not
use an Azure CLI login, client secret, subscription key, or runner identity.

## Enable after bootstrap, budget decision and permission verification

Add to the server's private `.env.aws`:

```dotenv
REPOPILOT_AZURE_RUNNER_ENABLED=true
REPOPILOT_AZURE_RUNNER_RESOURCE_ID=/subscriptions/YOUR_UUID/resourceGroups/repopilot/providers/Microsoft.Compute/virtualMachines/repopilot-runner
REPOPILOT_AZURE_RUNNER_IDLE_SECONDS=600
REPOPILOT_AZURE_RUNNER_BOOT_TIMEOUT_SECONDS=600
REPOPILOT_AZURE_RUNNER_LOCK_PATH=/opt/repopilot/data/runner-controller.lock
```

Keep the SSH sandbox host/image settings from AWS.md. The API does not start
VMs: only the single continuous trusted `worker run` process does. Run config
validation, then rebuild/update the API and worker from the reviewed revision:

```sh
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml build api worker
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml run --rm --no-deps api repopilot config validate
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml up -d api worker
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml logs --tail=80 worker
```

The worker acquires an exclusive Linux file lock on the shared app data volume.
All workers for this database/runner MUST use that same lock. Do not scale workers,
change the lock path, start manual workflow/evaluation workers, or run unrelated
workloads on this VM. The CLI rejects one-shot/eval commands when automation is on.
Do not use `--max-runs` in production: a continuously polling worker owns idle cleanup.

## Lifecycle and race safety

1. Read all queued/running runs from the durable DB (not a user-filtered list).
2. If work exists, start a deallocated/stopped runner, wait through Azure state
   transitions, and check remote Docker can inspect the exact prepared image.
3. Only then claim the queued run. During boot it remains `queued` in the UI.
   Cloud/auth/SSH/image failures leave it queued, log a sanitized warning and retry.
   A ten-minute boot timeout is per attempt, not a lost-run/failure timeout.
4. The same worker runs workflows synchronously. No shutdown check occurs during
   a workflow; other queued/running work also prevents idle shutdown. Completed
   runs awaiting human review do not hold the runner up; their workspaces live
   safely on the app host for approval/publication.
5. After ten continuously idle minutes, request **deallocate**, not OS shutdown
   or powerOff. Persist shutdown intent before the request. A new arrival during
   shutdown waits for deallocation to finish, restarts, checks Docker, then claims.
   The shutdown marker survives worker restarts. Never delete it to bypass a race.

After app/worker restart the idle grace starts again; stale running leases are
recovered by existing logic, not automatically replayed. No controller can stop
compute if it is down or Azure rejects deallocation. This is NOT a billing cap:
set monitoring for worker failure/old queue, runner left on, disk growth and costs.
Keep spending-limit protection and an operator-access route for manual deallocation.

## Live acceptance gate

No cloud changes are made by local tests. Before sharing runnable demos, verify:

- From deallocated: submit a mock-provider test run and confirm only one run is
  claimed after Docker/image readiness; a page refresh/sign-in preserves it.
- Leave a real long test active past the grace: VM must remain running. Queue a
  second user's run and verify it completes before idle timing begins.
- After the grace confirm Azure shows **Stopped (deallocated)**, not merely Stopped.
- Submit during deallocation, and restart the worker during that transition;
  verify the persistent marker prevents claim until a full stop/start completes.
- Simulate SSH/image/ARM permission failure: queued work must remain unclaimed,
  retry with sanitized logs, and resume after repair. No duplicate workflow/PR.
- Confirm reaper, runner-to-app/metadata denies, no secrets in the test archive,
  and the real repository's prepared dependencies, then do one bounded real run.
- Inspect subscription costs and credit balance again. Record actual boot/runtime
  and storage usage; update the calculator rather than assuming an empty-credit VM
  will be able to start. Deallocated VMs also have capacity-allocation risk.

References:
- https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/how-to-use-vm-token
- https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines/deallocate?view=rest-compute-2024-07-01
- https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices
