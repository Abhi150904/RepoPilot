from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from app.api.runs import FreeRunsExhausted, RunLimits, RunStore
from app.api.schemas import RunRequest
from app.auth.models import RunOwner
from app.services.run_service import RepoPilotRunService


LIMITS = RunLimits(max_active=10, max_daily=100, max_lifetime=2)
OWNER = RunOwner(123, "first-user")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    value = RunStore(database_url=f"sqlite:///{tmp_path / 'runs.db'}" if request.param == "sqlite" else None)
    yield value
    value.close()


def create(store, key=None, owner=OWNER):
    return store.create_result({"issue": "Example issue"}, owner=owner, limits=LIMITS, idempotency_key=key).run


def execute(store, run):
    store.mark_running(run.run_id, worker_id="worker")
    assert store.begin_execution(run.run_id, worker_id="worker")


def test_lifetime_limit_is_atomic_and_idempotent(store):
    first = create(store, "first")
    assert create(store, "first").run_id == first.run_id
    assert store.introductory_usage(123) == {"total": 2, "used": 0, "reserved": 1, "remaining": 1}
    execute(store, first)
    store.mark_failed(first.run_id, RuntimeError("Workflow failed after starting"))
    second = create(store)
    execute(store, second)
    store.mark_failed(second.run_id, RuntimeError("Workflow failed after starting"))
    with pytest.raises(FreeRunsExhausted):
        create(store)
    assert store.introductory_usage(123) == {"total": 2, "used": 2, "reserved": 0, "remaining": 0}
    assert store.introductory_usage(456)["remaining"] == 2


def test_failure_before_execution_releases_reservation(store):
    run = create(store)
    store.mark_running(run.run_id, worker_id="worker")
    store.mark_failed(run.run_id, RuntimeError("GitHub credential setup failed"))
    assert store.introductory_usage(123)["remaining"] == 2
    assert not store.begin_execution(run.run_id, worker_id="worker")


def test_execution_marker_is_fenced_and_only_written_once(store):
    run = create(store)
    store.mark_running(run.run_id, worker_id="worker")
    assert not store.begin_execution(run.run_id, worker_id="another-worker")
    assert store.introductory_usage(123)["used"] == 0
    assert store.begin_execution(run.run_id, worker_id="worker")
    assert not store.begin_execution(run.run_id, worker_id="worker")
    assert store.introductory_usage(123)["used"] == 1


@pytest.mark.parametrize("started", [True, False])
def test_worker_recovery_preserves_or_releases_allowance(store, started):
    run = create(store)
    store.mark_running(run.run_id, worker_id="worker", lease_seconds=1)
    if started:
        assert store.begin_execution(run.run_id, worker_id="worker")
    store.recover_stale_running_runs(stale_before=datetime.now(timezone.utc) + timedelta(days=1))
    assert store.introductory_usage(123)["remaining"] == (1 if started else 2)
    assert not store.begin_execution(run.run_id, worker_id="worker")


def test_concurrent_requests_cannot_reserve_more_than_two(store):
    def request(_):
        try:
            create(store)
            return True
        except FreeRunsExhausted:
            return False

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(request, range(12))) == 2
    assert store.introductory_usage(123)["reserved"] == 2


def test_usage_survives_restart_and_login_change(tmp_path):
    url = f"sqlite:///{tmp_path / 'persistent.db'}"
    first = RunStore(database_url=url)
    create(first)
    first.close()
    restarted = RunStore(database_url=url)
    assert restarted.introductory_usage(123)["remaining"] == 1
    create(restarted, owner=RunOwner(123, "renamed-login"))
    with pytest.raises(FreeRunsExhausted):
        create(restarted)
    restarted.close()


@pytest.mark.parametrize("after_start", [True, False])
def test_service_consumes_only_after_setup_succeeds(store, monkeypatch, after_start):
    import app.services.run_service as module

    class Workflow:
        def invoke(self, value):
            raise RuntimeError("Workflow execution failed")

    def build():
        if not after_start:
            raise RuntimeError("Could not prepare workflow")
        return Workflow()

    monkeypatch.setattr(module, "build_workflow", build)
    service = RepoPilotRunService(run_store=store, heartbeat_interval_seconds=0)
    run = service.create_run(RunRequest(issue="Example issue"), owner=OWNER, limits=LIMITS)
    result = service.execute_next_queued()
    assert result.run_id == run.run_id
    assert result.lifecycle_status == "failed"
    assert store.introductory_usage(123)["remaining"] == (1 if after_start else 2)


def test_review_refresh_and_publication_do_not_consume_another_attempt(store):
    from app.api.schemas import PublishRequest, RunArtifacts, RunResponse
    run = create(store)
    execute(store, run)
    store.mark_completed(run.run_id, RunResponse(status="awaiting_approval", next_action="await_approval",
        summary="Review ready", artifacts=RunArtifacts(), run_summary={}, result={}))
    service = RepoPilotRunService(run_store=store, heartbeat_interval_seconds=0)
    before = store.introductory_usage(123)
    service.get_result(run.run_id)
    service.reject_run(run.run_id)
    from app.services.run_service import RunServiceError
    with pytest.raises(RunServiceError, match="approved before publication"):
        service.publish_run(run.run_id, PublishRequest(mode="dry_run"))
    assert store.introductory_usage(123) == before


def test_allowance_migration_preserves_credit_ledger_and_existing_usage(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    import sqlalchemy as sa
    from app.services.billing import BillingAccount, BillingCheckout, BillingEntry, BillingEvent

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("REPOPILOT_DATABASE_URL", url)
    engine = create_engine(url)
    metadata = sa.MetaData()
    runs = sa.Table("runs", metadata,
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("owner_github_user_id", sa.BigInteger()),
        sa.Column("lifecycle_status", sa.String(32)))
    events = sa.Table("run_events", metadata, sa.Column("run_id", sa.String(64)),
                      sa.Column("event_type", sa.String(128)))
    metadata.create_all(engine)
    for model in (BillingAccount, BillingCheckout, BillingEntry, BillingEvent):
        model.__table__.create(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(runs.insert(), [
            {"run_id": "completed", "owner_github_user_id": 123, "lifecycle_status": "completed"},
            {"run_id": "failed", "owner_github_user_id": 123, "lifecycle_status": "failed"},
            {"run_id": "setup-failed", "owner_github_user_id": 123, "lifecycle_status": "failed"},
            {"run_id": "queued", "owner_github_user_id": 456, "lifecycle_status": "queued"},
            {"run_id": "anonymous", "owner_github_user_id": None, "lifecycle_status": "completed"}])
        connection.execute(events.insert(), {"run_id": "failed", "event_type": "run.started"})
        connection.execute(BillingEntry.__table__.insert(), [
            {"id": "purchase", "user_id": 123, "source": "purchase:old", "kind": "purchase", "delta": 5, "created_at": now},
            {"id": "spent", "user_id": 123, "source": "demo:old", "kind": "simulation", "delta": -1, "created_at": now}])
    config = Config("backend/alembic.ini")
    try:
        command.stamp(config, "20261019_0007")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            states = dict(connection.execute(sa.text("SELECT run_id, intro_state FROM runs")).all())
            assert states == {"completed": "consumed", "failed": "consumed", "setup-failed": "released",
                              "queued": "reserved", "anonymous": None}
            assert connection.scalar(sa.text("SELECT SUM(delta) FROM billing_entries")) == 4
        command.downgrade(config, "20261019_0007")
        assert "intro_state" not in {column["name"] for column in sa.inspect(engine).get_columns("runs")}
        assert "billing_entries" in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()
