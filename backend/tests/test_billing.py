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
from sqlalchemy import event, select
from standardwebhooks.webhooks import Webhook

from app.api.app import create_app
from app.api.runs import FreeRunsExhausted, IdempotencyConflict, RunLimits, RunRow, RunStore
from app.api.schemas import RunRequest
from app.auth.models import AuthorizedRepository, GitHubUser, RunOwner
from app.auth.sessions import InMemorySessionStore
from app.core.config import Settings
from app.services.billing import BillingEntry, BillingError, SandboxBilling
from app.services.run_service import RepoPilotRunService


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


OWNER = RunOwner(123, "test-user")


@pytest.fixture
def limits():
    return RunLimits(max_active=20, max_daily=100, max_lifetime=2, allow_paid=True)


@pytest.fixture
def run_store(billing):
    store = RunStore(database_url=billing.config.database_url)
    yield store
    store.close()


def admit(store, limits, *, key=None, owner=OWNER):
    return store.create_result({"issue": "Example issue"}, owner=owner,
                               limits=limits, idempotency_key=key)


def consume_free_runs(store, limits, *, owner=OWNER):
    for _ in range(2):
        run = admit(store, limits, owner=owner).run
        store.mark_running(run.run_id, worker_id="test-worker")
        assert store.begin_execution(run.run_id, worker_id="test-worker")
        store.mark_failed(run.run_id, RuntimeError("Workflow failed after execution started"))


def credit_entries(billing, user_id=123):
    with billing._factory()() as session:
        return sorted(session.execute(select(BillingEntry.source, BillingEntry.kind, BillingEntry.delta)
            .where(BillingEntry.user_id == user_id, BillingEntry.kind.in_(["run", "run_release"]))).all())


def intro_state(billing, run_id):
    with billing._factory()() as session:
        return session.scalar(select(RunRow.intro_state).where(RunRow.run_id == run_id))


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
    assert billing.status(123)["credit_balance"] == 0
    billing.webhook(*notification(billing, first["id"]))
    assert SandboxBilling(billing.config).status(123)["credit_balance"] == 5
    assert billing.status(456)["credit_balance"] == 0
    assert billing.status(456)["purchases"] == []


def test_duplicate_delivery_and_new_event_same_order_do_not_double_credit(billing):
    intent = paid(billing)
    event = notification(billing, intent)
    billing.webhook(*event)
    billing.webhook(*event)
    assert billing.status(123)["credit_balance"] == 5
    assert len(billing.status(123)["activity"]) == 1


def test_legacy_polar_signatures_remain_supported(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    billing.webhook(*notification(billing, intent, legacy=True))
    assert billing.status(123)["credit_balance"] == 5


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
    assert billing.status(123)["credit_balance"] == 0


@pytest.mark.parametrize("age", [601, -601])
def test_reject_stale_or_future_signed_messages(billing, age):
    intent = billing.checkout(123, str(uuid4()))["id"]
    with pytest.raises(BillingError, match="verification failed"):
        billing.webhook(*notification(billing, intent, age=age))
    assert billing.status(123)["credit_balance"] == 0


def test_tampered_or_malformed_signature(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    body, headers = notification(billing, intent)
    with pytest.raises(BillingError):
        billing.webhook(body + b" ", headers)
    headers["webhook-signature"] = "invalid"
    with pytest.raises(BillingError):
        billing.webhook(body, headers)


def test_paid_admission_debits_once_and_replays_after_restart(billing, run_store, limits):
    paid(billing)
    consume_free_runs(run_store, limits)
    assert billing.status(123)["credit_balance"] == 5
    assert credit_entries(billing) == []
    key = str(uuid4())
    first = admit(run_store, limits, key=key)
    assert first.created
    assert first.run.lifecycle_status == "queued"
    assert intro_state(billing, first.run.run_id) == "credit_reserved"
    assert billing.status(123)["credit_balance"] == 4
    expected = [(f"run:{first.run.run_id}:charge", "run", -1)]
    assert credit_entries(billing) == expected

    restarted = RunStore(database_url=billing.config.database_url)
    try:
        replay = admit(restarted, limits, key=key)
        assert not replay.created
        assert replay.run.run_id == first.run.run_id
        with pytest.raises(IdempotencyConflict):
            restarted.create_result({"issue": "Different issue"}, owner=OWNER,
                                    limits=limits, idempotency_key=key)
    finally:
        restarted.close()
    assert billing.status(123)["credit_balance"] == 4
    assert credit_entries(billing) == expected
    assert run_store.introductory_usage(123) == {"total": 2, "used": 2, "reserved": 0, "remaining": 0}


@pytest.mark.parametrize("after_start", [False, True])
def test_paid_service_failure_releases_only_before_execution(billing, run_store, limits, monkeypatch, after_start):
    import app.services.run_service as module

    paid(billing)
    consume_free_runs(run_store, limits)

    class Workflow:
        def invoke(self, value):
            raise RuntimeError("Workflow execution failed")

    def build():
        if not after_start:
            raise RuntimeError("Could not prepare workflow")
        return Workflow()

    monkeypatch.setattr(module, "build_workflow", build)
    service = RepoPilotRunService(run_store=run_store, heartbeat_interval_seconds=0)
    key = str(uuid4())
    request = RunRequest(issue="Example issue")
    run = service.create_run(request, owner=OWNER, limits=limits, idempotency_key=key)
    assert billing.status(123)["credit_balance"] == 4
    result = service.execute_next_queued()
    assert result.run_id == run.run_id
    assert result.lifecycle_status == "failed"
    assert intro_state(billing, run.run_id) == ("credit_consumed" if after_start else "credit_released")
    expected = [(f"run:{run.run_id}:charge", "run", -1)]
    if not after_start:
        expected.append((f"run:{run.run_id}:release", "run_release", 1))
    assert credit_entries(billing) == expected
    assert billing.status(123)["credit_balance"] == (4 if after_start else 5)

    run_store.mark_failed(run.run_id, RuntimeError("Repeated failure"))
    replay = service.create_run(request, owner=OWNER, limits=limits, idempotency_key=key)
    assert replay.run_id == run.run_id
    assert service.execute_next_queued() is None
    assert credit_entries(billing) == expected
    assert billing.status(123)["credit_balance"] == (4 if after_start else 5)


def test_refund_before_consumption_blocks_execution_then_releases_once(billing, run_store, limits):
    intent = paid(billing)
    consume_free_runs(run_store, limits)
    run = admit(run_store, limits).run
    billing.webhook(*notification(billing, intent, event_type="order.refunded", refunded_amount=500))
    assert billing.status(123)["credit_balance"] == -1
    run_store.mark_running(run.run_id, worker_id="test-worker")
    with pytest.raises(FreeRunsExhausted):
        run_store.begin_execution(run.run_id, worker_id="test-worker")
    assert intro_state(billing, run.run_id) == "credit_reserved"
    assert not any(event["event_type"] == "run.execution_started" for event in run_store.get(run.run_id).events)
    run_store.mark_failed(run.run_id, FreeRunsExhausted("Purchase was refunded"))
    run_store.mark_failed(run.run_id, RuntimeError("Repeated failure"))
    assert intro_state(billing, run.run_id) == "credit_released"
    assert billing.status(123)["credit_balance"] == 0
    assert credit_entries(billing) == [
        (f"run:{run.run_id}:charge", "run", -1),
        (f"run:{run.run_id}:release", "run_release", 1),
    ]
    with pytest.raises(FreeRunsExhausted):
        admit(run_store, limits)


def test_service_fails_refunded_queued_run_without_invoking_workflow(billing, run_store, limits, monkeypatch):
    import app.services.run_service as module

    intent = paid(billing)
    consume_free_runs(run_store, limits)
    invoked = []

    class Workflow:
        def invoke(self, value):
            invoked.append(value)
            raise AssertionError("Refunded credit must not execute a workflow")

    monkeypatch.setattr(module, "build_workflow", lambda: Workflow())
    service = RepoPilotRunService(run_store=run_store, heartbeat_interval_seconds=0)
    run = service.create_run(RunRequest(issue="Example issue"), owner=OWNER, limits=limits)
    billing.webhook(*notification(billing, intent, event_type="order.refunded", refunded_amount=500))
    result = service.execute_next_queued()
    assert result.run_id == run.run_id
    assert result.lifecycle_status == "failed"
    assert invoked == []
    assert not any(event["event_type"] == "run.execution_started" for event in result.events)
    assert intro_state(billing, run.run_id) == "credit_released"
    assert billing.status(123)["credit_balance"] == 0
    assert credit_entries(billing) == [
        (f"run:{run.run_id}:charge", "run", -1),
        (f"run:{run.run_id}:release", "run_release", 1),
    ]


def test_refund_after_consumption_reverses_pack_once_and_retains_charge(billing, run_store, limits):
    intent = paid(billing)
    consume_free_runs(run_store, limits)
    key = str(uuid4())
    run = admit(run_store, limits, key=key).run
    run_store.mark_running(run.run_id, worker_id="test-worker")
    assert run_store.begin_execution(run.run_id, worker_id="test-worker")
    assert not run_store.begin_execution(run.run_id, worker_id="test-worker")
    assert intro_state(billing, run.run_id) == "credit_consumed"
    for _ in range(2):
        billing.webhook(*notification(billing, intent, event_type="order.refunded", refunded_amount=500))
    assert billing.status(123)["credit_balance"] == -1
    run_store.mark_failed(run.run_id, RuntimeError("Workflow failed after execution started"))
    assert intro_state(billing, run.run_id) == "credit_consumed"
    assert admit(run_store, limits, key=key).run.run_id == run.run_id
    with pytest.raises(FreeRunsExhausted):
        admit(run_store, limits)
    billing.webhook(*notification(billing, intent))
    assert billing.status(123)["credit_balance"] == -1
    assert credit_entries(billing) == [(f"run:{run.run_id}:charge", "run", -1)]


def test_fully_reserved_pack_can_begin_execution_at_zero_balance(billing, run_store, limits):
    paid(billing)
    consume_free_runs(run_store, limits)
    runs = [admit(run_store, limits).run for _ in range(5)]
    assert billing.status(123)["credit_balance"] == 0
    for run in runs:
        run_store.mark_running(run.run_id, worker_id="test-worker")
        assert run_store.begin_execution(run.run_id, worker_id="test-worker")
        assert intro_state(billing, run.run_id) == "credit_consumed"
        run_store.mark_failed(run.run_id, RuntimeError("Execution failed"))
    assert billing.status(123)["credit_balance"] == 0
    assert credit_entries(billing) == sorted((f"run:{run.run_id}:charge", "run", -1) for run in runs)
    with pytest.raises(FreeRunsExhausted):
        admit(run_store, limits)


def test_out_of_order_refund_prevents_late_credit(billing):
    intent = billing.checkout(123, str(uuid4()))["id"]
    billing.webhook(*notification(billing, intent, event_type="order.refunded", refunded_amount=500))
    billing.webhook(*notification(billing, intent))
    assert billing.status(123)["credit_balance"] == 0


def test_checkout_does_not_follow_production_redirects(billing, monkeypatch):
    def post(client, url, **kwargs):
        return httpx.Response(201, json={"id": "checkout", "url": "https://polar.sh/checkout/live"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(BillingError, match="Could not open"):
        billing.checkout(123, str(uuid4()))
    assert billing.status(123)["purchases"][0]["state"] == "failed"


def test_billing_auth_checkout_csrf_and_payload_limits(billing):
    sessions = InMemorySessionStore()
    app = create_app(settings=billing.config, session_store=sessions, billing_service=billing)
    with TestClient(app) as client:
        payload = {"request_key": str(uuid4())}
        assert client.get("/billing").status_code == 401
        assert client.get("/usage").status_code == 401
        assert client.post("/billing/checkout", json=payload).status_code == 401
        auth = sessions.create_session(user=GitHubUser(123, "test-user"), oauth_access_token="test-token")
        client.cookies.set("repopilot_session", auth.session_id)
        assert client.get("/billing").status_code == 200
        assert client.post("/billing/checkout", json=payload).status_code == 403
        assert client.post("/billing/checkout", json=payload,
                           headers={"X-CSRF-Token": "invalid"}).status_code == 403
        assert billing.status(123)["purchases"] == []
        headers = {"X-CSRF-Token": auth.csrf_token}
        checkout = client.post("/billing/checkout", json=payload, headers=headers)
        assert checkout.status_code == 200
        assert client.post("/billing/checkout", json=payload, headers=headers).json() == checkout.json()
        assert len(billing.status(123)["purchases"]) == 1
        status = client.get("/billing").json()
        assert status["credit_balance"] == 0
        assert "demo_balance" not in status
        usage = client.get("/usage").json()
        assert usage["run_credits"] == 0
        assert "simulation_credits" not in usage
        assert client.post("/billing/webhook", content=b"x" * 262145).status_code == 413
        assert client.post("/billing/webhook", content=b"{}").status_code == 400


@pytest.mark.parametrize("authenticated", [False, True])
def test_removed_simulation_endpoints_return_404(billing, authenticated):
    sessions = InMemorySessionStore()
    app = create_app(settings=billing.config, session_store=sessions, billing_service=billing)
    with TestClient(app) as client:
        headers = {}
        if authenticated:
            auth = sessions.create_session(user=GitHubUser(123, "test-user"), oauth_access_token="test-token")
            client.cookies.set("repopilot_session", auth.session_id)
            headers["X-CSRF-Token"] = auth.csrf_token
        assert client.get("/simulations").status_code == 404
        assert client.post("/simulations", json={"request_key": str(uuid4())}, headers=headers).status_code == 404
        assert client.post("/billing/simulate", json={"request_key": str(uuid4())}, headers=headers).status_code == 404


def test_simulation_service_removed(billing):
    assert not hasattr(billing, "simulate")
    assert not hasattr(billing, "simulations")


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_paid_admissions_across_stores_do_not_double_debit(billing, run_store, limits, same_key):
    paid(billing)
    consume_free_runs(run_store, limits)
    other_store = RunStore(database_url=billing.config.database_url)
    key = str(uuid4())

    def spend(index):
        store = run_store if index % 2 else other_store
        try:
            return admit(store, limits, key=key if same_key else str(uuid4()))
        except FreeRunsExhausted:
            return None

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(spend, range(15)))
        admitted = [result for result in results if result is not None]
        expected = 1 if same_key else 5
        assert len(admitted) == (15 if same_key else 5)
        assert sum(result.created for result in admitted) == expected
        assert len({result.run.run_id for result in admitted}) == expected
        assert billing.status(123)["credit_balance"] == 5 - expected
        assert len(run_store.list(owner=OWNER)) == 2 + expected
        assert credit_entries(billing) == sorted(
            (f"run:{run_id}:charge", "run", -1) for run_id in {result.run.run_id for result in admitted})
        if not same_key:
            with pytest.raises(FreeRunsExhausted):
                admit(run_store, limits)
    finally:
        other_store.close()


def test_failed_paid_admission_rolls_back_run_and_ledger_together(billing, run_store, limits):
    paid(billing)
    consume_free_runs(run_store, limits)
    before = {run.run_id for run in run_store.list(owner=OWNER)}
    key = str(uuid4())

    def fail_insert(connection, cursor, statement, parameters, context, executemany):
        if not context.isinsert or context.compiled.statement.table.name != RunRow.__tablename__:
            return
        # The debit is already flushed when persisting the real run fails.
        assert connection.scalar(select(BillingEntry.delta).where(BillingEntry.kind == "run")) == -1
        assert len(connection.execute(select(RunRow.run_id)).all()) == 2
        raise RuntimeError("Cannot insert paid run")

    event.listen(run_store._engine, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="Cannot insert paid run"):
            admit(run_store, limits, key=key)
    finally:
        event.remove(run_store._engine, "before_cursor_execute", fail_insert)
    assert billing.status(123)["credit_balance"] == 5
    assert credit_entries(billing) == []
    assert {run.run_id for run in run_store.list(owner=OWNER)} == before
    retry = admit(run_store, limits, key=key)
    assert retry.created
    assert billing.status(123)["credit_balance"] == 4
    assert credit_entries(billing) == [(f"run:{retry.run.run_id}:charge", "run", -1)]


def test_failed_run_insertion_rolls_back_reserved_credit(billing, run_store, limits, monkeypatch):
    import app.api.runs as module

    paid(billing)
    consume_free_runs(run_store, limits)
    before = {run.run_id for run in run_store.list(owner=OWNER)}
    key = str(uuid4())

    def fail(*args, **kwargs):
        raise RuntimeError("Cannot persist run owner")

    with monkeypatch.context() as patch:
        patch.setattr(module, "_upsert_owner_metadata", fail)
        with pytest.raises(RuntimeError, match="Cannot persist run owner"):
            admit(run_store, limits, key=key)
    assert billing.status(123)["credit_balance"] == 5
    assert credit_entries(billing) == []
    assert {run.run_id for run in run_store.list(owner=OWNER)} == before
    retry = admit(run_store, limits, key=key)
    assert retry.created
    assert billing.status(123)["credit_balance"] == 4
    assert credit_entries(billing) == [(f"run:{retry.run.run_id}:charge", "run", -1)]


def test_paid_admission_cannot_spend_another_accounts_credits(billing, run_store, limits):
    paid(billing)
    consume_free_runs(run_store, limits)
    other = RunOwner(456, "other-user")
    consume_free_runs(run_store, limits, owner=other)
    key = str(uuid4())
    run = admit(run_store, limits, key=key).run
    with pytest.raises(FreeRunsExhausted):
        admit(run_store, limits, key=key, owner=other)
    assert billing.status(123)["credit_balance"] == 4
    assert billing.status(456)["credit_balance"] == 0
    assert billing.status(456)["purchases"] == []
    assert billing.status(456)["activity"] == []
    assert credit_entries(billing, 456) == []
    assert len(run_store.list(owner=other)) == 2
    run_store.mark_failed(run.run_id, RuntimeError("Setup failed"))
    assert billing.status(123)["credit_balance"] == 5
    assert billing.status(456)["credit_balance"] == 0


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
        command.upgrade(config, "20261019_0007")
        assert {"billing_accounts", "billing_checkouts", "billing_entries", "billing_events"} <= set(inspect(engine).get_table_names())
        command.downgrade(config, "20261010_0006")
        assert "billing_entries" not in inspect(engine).get_table_names()
        assert "runs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_purchased_credits_admit_real_queued_run_and_usage_is_account_scoped(billing, run_store):
    class GitHub:
        def authorize_repository(self, **kwargs):
            return AuthorizedRepository("owner/repo", 1)

    settings = billing.config.model_copy(update={"inline_run_execution": False})
    service = RepoPilotRunService(run_store=run_store, heartbeat_interval_seconds=0)
    sessions = InMemorySessionStore()
    auth = sessions.create_session(user=GitHubUser(123, "test-user"), oauth_access_token="test-token")
    paid(billing)
    with TestClient(create_app(settings=settings, service=service, session_store=sessions,
                              billing_service=billing, github_app_service=GitHub())) as client:
        client.cookies.set("repopilot_session", auth.session_id)
        headers = {"X-CSRF-Token": auth.csrf_token}
        payload = {"repository": "owner/repo", "issue_number": 1}
        for _ in range(2):
            response = client.post("/runs", json=payload, headers=headers)
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            run_store.mark_running(run_id, worker_id="test-worker")
            assert run_store.begin_execution(run_id, worker_id="test-worker")
            run_store.mark_failed(run_id, RuntimeError("Workflow failed after execution started"))
        assert client.get("/usage").json()["run_credits"] == 5
        headers["Idempotency-Key"] = str(uuid4())
        response = client.post("/runs", json=payload, headers=headers)
        assert response.status_code == 202
        run = response.json()
        assert run["lifecycle_status"] == "queued"
        assert intro_state(billing, run["run_id"]) == "credit_reserved"
        replay = client.post("/runs", json=payload, headers=headers)
        assert replay.status_code == 202
        assert replay.json()["run_id"] == run["run_id"]
        usage = client.get("/usage").json()
        assert usage["introductory"]["remaining"] == 0
        assert usage["run_credits"] == 4
        assert "simulation_credits" not in usage
        status = client.get("/billing").json()
        assert status["credit_balance"] == 4
        assert "demo_balance" not in status
        assert len(client.get("/runs").json()) == 3
        assert credit_entries(billing) == [(f"run:{run['run_id']}:charge", "run", -1)]

        other = sessions.create_session(user=GitHubUser(456, "other-user"), oauth_access_token="other-token")
        client.cookies.set("repopilot_session", other.session_id)
        assert client.get("/runs").json() == []
        assert client.get(f"/runs/{run['run_id']}").status_code == 404
        assert client.get("/billing").json()["credit_balance"] == 0
        assert client.get("/billing").json()["activity"] == []
        assert client.get("/usage").json()["run_credits"] == 0
        assert client.get("/usage").json()["introductory"]["remaining"] == 2
