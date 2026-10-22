from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from standardwebhooks.webhooks import Webhook

from app.api.app import create_app
from app.auth.models import GitHubUser
from app.auth.sessions import InMemorySessionStore
from app.core.config import Settings
from app.services.billing import BillingError, SandboxBilling


@pytest.fixture
def billing(tmp_path, monkeypatch):
    config = Settings(_env_file=None, hosted_mode=True, billing_enabled=True,
        database_url=f"sqlite:///{tmp_path / 'billing.db'}", public_base_url="https://frontend.test",
        polar_access_token="test-only-token",
        polar_webhook_secret="whsec_" + base64.b64encode(b"test-only-key-not-a-real-secret!!").decode(),
        polar_product_id="test-product", polar_organization_id="test-org")

    original_post = httpx.Client.post

    def post(client, url, **kwargs):
        if not str(url).startswith("https://sandbox-api.polar.sh"):
            return original_post(client, url, **kwargs)
        assert url == "https://sandbox-api.polar.sh/v1/checkouts/"
        assert kwargs["headers"]["Polar-Version"] == "2026-04"
        payload = kwargs["json"]
        assert payload["products"] == ["test-product"]
        assert payload["external_customer_id"].startswith("github:")
        assert payload["success_url"] == "https://frontend.test/billing?checkout=returned"
        intent = payload["metadata"]["repopilot_intent"]
        return httpx.Response(201, json={"id": intent, "url": f"https://sandbox.polar.sh/checkout/{intent}"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    return SandboxBilling(config)


def notification(billing, intent, *, event_type="order.paid", event_id=None, age=0, legacy=False, **overrides):
    data = {"id": "order-" + intent, "checkout_id": intent, "product_id": "test-product",
        "customer": {"organization_id": "test-org", "external_id": "github:123"},
        "metadata": {"repopilot_intent": intent}, "paid": True, "status": "paid",
        "net_amount": 500, "currency": "usd", "subscription_id": None, "refunded_amount": 0}
    data.update(overrides)
    body = json.dumps({"type": event_type, "data": data}).encode()
    now = datetime.now(timezone.utc) - timedelta(seconds=age)
    event_id = event_id or uuid4().hex
    secret = billing.config.polar_webhook_secret
    key = base64.b64encode(secret.encode()).decode() if legacy else secret
    signature = Webhook(key).sign(
        event_id, now, body.decode())
    return body, {"webhook-id": event_id, "webhook-timestamp": str(int(now.timestamp())),
                  "webhook-signature": signature}


def paid(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    billing.webhook(*notification(billing, intent))
    return intent


def test_sandbox_only_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, polar_server="production")
    config = Settings(_env_file=None)
    assert SandboxBilling(config).status(123)["enabled"] is False
    with pytest.raises(BillingError, match="not configured"):
        SandboxBilling(config).checkout(123, str(uuid4()))


def test_credit_only_after_verified_webhook_and_persisted_restart(billing):
    key = str(uuid4())
    first = billing.checkout(123, key)
    assert billing.checkout(123, key) == first
    assert billing.status(123)["demo_balance"] == 0
    billing.webhook(*notification(billing, first["id"]))
    assert SandboxBilling(billing.config).status(123)["demo_balance"] == 5
    assert billing.status(456)["demo_balance"] == 0
    assert billing.status(456)["purchases"] == []


def test_duplicate_delivery_and_new_event_same_order_do_not_double_credit(billing):
    intent = paid(billing)
    event = notification(billing, intent)
    billing.webhook(*event)
    billing.webhook(*event)
    assert billing.status(123)["demo_balance"] == 5
    assert len(billing.status(123)["activity"]) == 1


def test_legacy_polar_signatures_remain_supported(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    billing.webhook(*notification(billing, intent, legacy=True))
    assert billing.status(123)["demo_balance"] == 5


@pytest.mark.parametrize("overrides", [
    {"product_id": "other-product"},
    {"customer": {"organization_id": "other-org", "external_id": "github:123"}},
    {"customer": {"organization_id": "test-org", "external_id": "github:456"}},
    {"checkout_id": "other-checkout"}, {"paid": False}, {"status": "pending"},
    {"currency": "eur"}, {"net_amount": 1}, {"subscription_id": "a-subscription"},
])
def test_reject_mismatched_orders(billing, overrides):
    intent = billing.checkout(123, str(uuid4()))["id"]
    with pytest.raises(BillingError):
        billing.webhook(*notification(billing, intent, **overrides))
    assert billing.status(123)["demo_balance"] == 0


@pytest.mark.parametrize("age", [601, -601])
def test_reject_stale_or_future_signed_messages(billing, age):
    intent = billing.checkout(123, str(uuid4()))["id"]
    with pytest.raises(BillingError, match="verification failed"):
        billing.webhook(*notification(billing, intent, age=age))
    assert billing.status(123)["demo_balance"] == 0


def test_tampered_or_malformed_signature(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    body, headers = notification(billing, intent)
    with pytest.raises(BillingError):
        billing.webhook(body + b" ", headers)
    headers["webhook-signature"] = "invalid"
    with pytest.raises(BillingError):
        billing.webhook(body, headers)


def test_simulation_is_idempotent_and_cannot_overdraw(billing):
    paid(billing)
    key = str(uuid4())
    assert billing.simulate(123, key)["simulated"] is True
    assert billing.simulate(123, key)["demo_balance"] == 4
    for _ in range(4):
        billing.simulate(123, str(uuid4()))
    with pytest.raises(BillingError, match="No demo attempts"):
        billing.simulate(123, str(uuid4()))
    with pytest.raises(BillingError):
        billing.simulate(456, key)


def test_refund_reverses_pack_once_even_after_spending(billing):
    intent = paid(billing)
    billing.simulate(123, str(uuid4()))
    for _ in range(2):
        billing.webhook(*notification(billing, intent, event_type="order.refunded", refunded_amount=500))
    assert billing.status(123)["demo_balance"] == -1
    with pytest.raises(BillingError):
        billing.simulate(123, str(uuid4()))
    billing.webhook(*notification(billing, intent))
    assert billing.status(123)["demo_balance"] == -1


def test_out_of_order_refund_prevents_late_credit(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    billing.webhook(*notification(billing, intent, event_type="order.refunded", refunded_amount=500))
    billing.webhook(*notification(billing, intent))
    assert billing.status(123)["demo_balance"] == 0


def test_checkout_does_not_follow_production_redirects(billing, monkeypatch):
    def post(client, url, **kwargs):
        return httpx.Response(201, json={"id": "checkout", "url": "https://polar.sh/checkout/live"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(BillingError, match="Could not open"):
        billing.checkout(123, str(uuid4()))
    assert billing.status(123)["purchases"][0]["state"] == "failed"


def test_billing_auth_csrf_and_payload_limits(billing):
    sessions = InMemorySessionStore()
    app = create_app(settings=billing.config, session_store=sessions, billing_service=billing)
    with TestClient(app) as client:
        assert client.get("/billing").status_code == 401
        assert client.post("/billing/simulate", json={"request_key": str(uuid4())}).status_code == 401
        auth = sessions.create_session(user=GitHubUser(123, "test-user"), oauth_access_token="test-token")
        client.cookies.set("repopilot_session", auth.session_id)
        assert client.get("/billing").status_code == 200
        assert client.post("/billing/simulate", json={"request_key": str(uuid4())}).status_code == 403
        assert client.post("/billing/webhook", content=b"x" * 262145).status_code == 413
        assert client.post("/billing/webhook", content=b"{}").status_code == 400
        paid(billing)
        # A billing simulation never creates a queued real run.
        result = client.post("/billing/simulate", json={"request_key": str(uuid4())},
                             headers={"X-CSRF-Token": auth.csrf_token})
        assert result.status_code == 200
        assert client.get("/runs").json() == []


def test_concurrent_spending_cannot_overdraw(billing):
    paid(billing)

    def spend(_):
        try:
            billing.simulate(123, str(uuid4()))
            return True
        except BillingError as error:
            assert error.code == "demo_balance_empty"
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(spend, range(15))) == 5
    assert billing.status(123)["demo_balance"] == 0


def test_billing_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("REPOPILOT_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    engine = create_engine(url)
    try:
        # Prior migrations include PostgreSQL-only ALTER CONSTRAINT operations.
        # Exercise this additive migration over the previous revision's run table.
        from app.api.runs import RunRow
        RunRow.__table__.create(engine)
        command.stamp(config, "20261010_0006")
        command.upgrade(config, "head")
        assert {"billing_accounts", "billing_checkouts", "billing_entries", "billing_events"} <= set(inspect(engine).get_table_names())
        command.downgrade(config, "20261010_0006")
        assert "billing_entries" not in inspect(engine).get_table_names()
        assert "runs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
