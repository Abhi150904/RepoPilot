from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from app.api.runs import IdempotencyConflict, RunLimitExceeded, RunLimits, RunStore
from app.api.schemas import RunRequest
from app.auth.models import RunOwner
from app.services.run_service import RepoPilotRunService, RunServiceError


OWNER = RunOwner(101, "demo-user", repository="example/first")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "sqlite":
        return RunStore(engine=create_engine(f"sqlite:///{tmp_path / 'runs.db'}"))
    return RunStore()


def test_active_limit_counts_queued_and_running_across_repositories(store):
    limits = RunLimits(max_active=1, max_daily=5)
    run = store.create_result({}, owner=OWNER, limits=limits).run
    for status in ("queued", "running"):
        if status == "running":
            store.mark_running(run.run_id)
        with pytest.raises(RunLimitExceeded, match="queued or running"):
            store.create_result({}, owner=RunOwner(101, "renamed-user", repository="example/second"), limits=limits)
    store.mark_failed(run.run_id, RuntimeError("test failure"))
    assert store.create_result({}, owner=OWNER, limits=limits).created


def test_daily_limit_counts_failures_and_is_separate_for_each_user(store):
    limits = RunLimits(max_active=1, max_daily=2)
    for _ in range(2):
        run = store.create_result({}, owner=OWNER, limits=limits).run
        store.mark_failed(run.run_id, RuntimeError("test failure"))
    with pytest.raises(RunLimitExceeded, match="24 hours"):
        store.create_result({}, owner=OWNER, limits=limits)
    assert store.create_result({}, owner=RunOwner(202, "other"), limits=limits).created
    assert len(store.list(owner=OWNER)) == 2


def test_idempotent_replay_does_not_consume_a_slot_or_bypass_payload_conflict(store):
    limits = RunLimits(max_active=1, max_daily=1)
    first = store.create_result({"issue": "one"}, owner=OWNER, idempotency_key="same", limits=limits)
    replay = store.create_result({"issue": "one"}, owner=OWNER, idempotency_key="same", limits=limits)
    assert not replay.created
    assert replay.run.run_id == first.run.run_id
    with pytest.raises(IdempotencyConflict):
        store.create_result({"issue": "two"}, owner=OWNER, idempotency_key="same", limits=limits)


def test_rolling_window_expires_after_24_hours(store, monkeypatch):
    import app.api.runs as runs_module

    now = datetime(2026, 10, 17, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(runs_module, "_now", lambda: now)
    limits = RunLimits(max_active=1, max_daily=1)
    run = store.create_result({}, owner=OWNER, limits=limits).run
    store.mark_failed(run.run_id, RuntimeError("test failure"))
    now += timedelta(hours=23)
    with pytest.raises(RunLimitExceeded):
        store.create_result({}, owner=OWNER, limits=limits)
    now += timedelta(hours=2)
    assert store.create_result({}, owner=OWNER, limits=limits).created


def test_limits_require_a_trusted_owner_but_do_not_affect_local_runs(store):
    with pytest.raises(ValueError, match="authenticated owner"):
        store.create_result({}, limits=RunLimits(1, 1))
    for _ in range(6):
        assert store.create_result({}).created


def test_sqlite_admission_is_atomic_across_store_instances(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'shared.db'}"
    first = RunStore(database_url=database_url)
    second = RunStore(database_url=database_url)

    def create(store):
        try:
            store.create_result({}, owner=OWNER, limits=RunLimits(1, 5))
            return "created"
        except RunLimitExceeded:
            return "limited"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, [first, second])) == ["created", "limited"]
    assert len(RunStore(database_url=database_url).list(owner=OWNER)) == 1


def test_service_returns_actionable_quota_error():
    service = RepoPilotRunService()
    service.create_run(RunRequest(issue="First"), owner=OWNER, limits=RunLimits(1, 5))
    with pytest.raises(RunServiceError) as caught:
        service.create_run(RunRequest(issue="Second"), owner=OWNER, limits=RunLimits(1, 5))
    assert caught.value.status_code == 429
    assert caught.value.code == "run_limit_reached"
