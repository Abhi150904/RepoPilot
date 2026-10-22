# Polar sandbox billing

This is a payment integration demonstration, not a commercial checkout. Live
Polar mode is rejected by settings validation. The API host and hosted-checkout
host are fixed to Polar sandbox. Sandbox tokens cannot be used with Polar's
production API.

## Product boundaries

- GitHub sign-in and CSRF protection are required for checkout and spending.
- A one-time USD 5.00 test pack grants five **demo** attempts.
- Only a signature-verified `order.paid` webhook grants attempts. Returning from
  checkout does not grant anything.
- Demo attempts run a fixed, explicitly simulated example. They cannot call an
  LLM, enqueue a real run, start Azure, change a repository or publish a PR.
- Real AI runs retain their existing daily/concurrency limits and spend budget.
  The proposed two-lifetime introductory real attempts are a separate follow-up;
  this billing slice does not implement or reset that allowance.
- Each purchase, refund and simulation is stored in a separate billing ledger.
  Order, checkout and action identifiers prevent duplicate credits/spending.
- Any positive refund revokes the entire demo pack, including partial refunds.
  Already-spent attempts can leave a negative demo balance. A refund received
  before payment confirmation prevents a late payment event granting credits.

## Sandbox setup

1. Open <https://sandbox.polar.sh> and create a dedicated sandbox account and
   organization. Do not onboard a live merchant account.
2. Create one public, non-recurring, fixed-price product called
   `RepoPilot Demo Pack`, priced at **USD 5.00**. Do not add subscription prices,
   discounts, free trials or variable pricing.
3. Record its product ID and organization ID. These are not secrets.
4. Create a sandbox organization access token with `checkouts:write` only. Store
   it directly in the app VM's private environment file, not in Git or chat.
5. Create a webhook endpoint in that sandbox organization:
   `https://repopilot.duckdns.org/billing/webhook`.
   Subscribe to `order.paid` and `order.refunded`. Copy the endpoint's signing
   secret directly to the same private environment file.
   Select webhook API version `2026-04` to match the backend's explicit
   `Polar-Version: 2026-04` checkout request header.

Use the endpoint's **Raw / JSON** delivery format and keep the signing secret
exactly as shown by Polar. The verifier supports both current Standard Webhooks
secrets and legacy Polar HMAC secrets; both require valid signatures and recent
timestamps. Do not encode or edit the secret yourself.

Private app VM environment entries (names only; use your actual sandbox values):

```dotenv
REPOPILOT_BILLING_ENABLED=true
REPOPILOT_POLAR_SERVER=sandbox
REPOPILOT_POLAR_ACCESS_TOKEN=<sandbox organization token>
REPOPILOT_POLAR_WEBHOOK_SECRET=<sandbox endpoint signing secret>
REPOPILOT_POLAR_PRODUCT_ID=<sandbox product ID>
REPOPILOT_POLAR_ORGANIZATION_ID=<sandbox organization ID>
```

`REPOPILOT_PUBLIC_BASE_URL` must remain the actual frontend URL. Do not put any
Polar secret in a `NEXT_PUBLIC_` variable or browser code. Billing is disabled by
default and remains unavailable until all required settings are present.

Official references:
[sandbox](https://polar.sh/docs/integrate/sandbox),
[checkout creation](https://polar.sh/docs/api-reference/checkouts/create-session),
[webhooks](https://polar.sh/docs/integrate/webhooks/endpoints).

## Deployment

Commit, review and merge the code before deploying. On the **app VM SSH terminal**,
from `~/RepoPilot`, with no running real workflow:

```bash
git pull --ff-only origin main
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml build migrate api worker
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml run --rm migrate
sudo docker compose --env-file .env.aws -f deploy/compose.aws.yml up -d api worker
sudo python3 deploy/monitor_production.py --check-only
```

The migration adds only billing tables. No existing runs or balances are removed.
Vercel must deploy the matching frontend commit from main. No frontend secret or
new public port is required. The runner VM does not need rebuilding.

## Acceptance checks

1. Sign in and open `/billing`; verify zero demo balance.
2. Open test checkout. Confirm the hostname is `sandbox.polar.sh`. Use only Polar's
   documented test card `4242 4242 4242 4242`, a future expiry and a test CVC.
3. Verify a paid purchase and balance five appear after webhook delivery.
4. Run one simulation: balance becomes four; the output says it is simulated.
   Verify no new real run, PR or Azure start occurs.
5. Redeliver the paid event from the sandbox dashboard: balance remains four.
6. Sign in as another GitHub user: no access to the first user's purchase/balance.
7. Refund the test purchase: the entire pack is revoked once. No real money moves.
8. Cancel a new checkout: no extra demo attempts appear. A declined test card is
   handled inside Polar checkout; it must not add attempts.

The dashboard lists at most twenty recent purchases and ledger entries. A return
from checkout triggers bounded polling for a minute; if confirmation is delayed,
use Refresh. A pending checkout is not proof of payment. Failed API creation is
shown as failed; abandoned checkout intents remain pending locally. At most five
pending checkout creations per user per UTC day are allowed. Automatic expiry
reconciliation is not implemented in this first slice.

For suspected missing credits, inspect the sandbox webhook delivery status and
redeliver after correcting configuration. Do not manually edit balances or grant
attempts based on a success-page screenshot. A provider outage returns a generic
error and grants nothing. Unknown or unrelated signed events grant nothing.

## Local checks

```powershell
python -m pip install -e .
python -m pytest backend/tests/test_billing.py -q -p no:cacheprovider
```

Tests use SQLite and fake Polar responses, not the public API. PostgreSQL account
row locking is used in deployment; verify webhook redelivery and simultaneous
spending against a disposable PostgreSQL database before opening the demo to
untrusted traffic. No actual sandbox checkout is claimed tested without the
account, product and endpoint setup above.
