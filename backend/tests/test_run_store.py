from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine

from app.api.runs import IdempotencyConflict, RunStore
from app.auth.models import RunOwner


def test_sql_run_store_persists_run_records() -> None:
    database_path = Path(f".repopilot-test-{uuid4().hex}.db").resolve()
    store = None
    reloaded = None
    try:
        database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
        store = RunStore(database_url=database_url)

        created = store.create(
            {"repository": "octo/repo", "issue_number": 1},
            request_id="trace-1",
            owner=RunOwner(github_user_id=101, github_login="octo", installation_id=123),
        )

        reloaded = RunStore(database_url=database_url)
        run = reloaded.get(created.run_id)

        assert run is not None
        assert run.run_id == created.run_id
        assert run.lifecycle_status == "queued"
        assert run.publication_status == "not_started"
        assert run.request == {"repository": "octo/repo", "issue_number": 1}
        assert [event["event_type"] for event in run.events] == ["run.created", "run.queued"]
        assert reloaded.get_request_id(created.run_id) == "trace-1"
        assert reloaded.get_owner(created.run_id) == RunOwner(
            github_user_id=101,
            github_login="octo",
            installation_id=123,
        )
    finally:
        if store is not None:
            store.close()
        if reloaded is not None:
            reloaded.close()
        if database_path.exists():
            database_path.unlink()


def test_sql_run_store_idempotency_reuses_same_payload() -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))

    first = store.create(
        {"repository": "octo/repo", "issue_number": 1},
        idempotency_key="idem-1",
    )
    second = store.create(
        {"repository": "octo/repo", "issue_number": 1},
        idempotency_key="idem-1",
    )

    assert second.run_id == first.run_id


def test_sql_run_store_idempotency_conflicts_for_different_payload() -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))

    store.create({"repository": "octo/repo", "issue_number": 1}, idempotency_key="idem-1")

    try:
        store.create({"repository": "octo/repo", "issue_number": 2}, idempotency_key="idem-1")
    except IdempotencyConflict:
        pass
    else:
        raise AssertionError("Expected idempotency conflict")


def test_sql_run_store_interrupts_running_runs_on_restart() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = RunStore(engine=engine)
    run = store.create({"issue": "Fix login"})
    store.mark_running(run.run_id)

    restarted = RunStore(engine=engine)
    recovered = restarted.get(run.run_id)

    assert recovered is not None
    assert recovered.lifecycle_status == "interrupted"
    assert recovered.error is not None
    assert recovered.error.code == "run_interrupted"
    assert "run.interrupted" in [event["event_type"] for event in recovered.events]


def test_sql_run_store_claims_only_one_queued_run() -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))
    first = store.create({"issue": "First"})
    second = store.create({"issue": "Second"})

    claimed = store.claim_next_queued()

    assert claimed is not None
    assert claimed.run_id == first.run_id
    assert claimed.lifecycle_status == "running"
    assert store.get(first.run_id).lifecycle_status == "running"  # type: ignore[union-attr]
    assert store.get(second.run_id).lifecycle_status == "queued"  # type: ignore[union-attr]


def test_sql_run_store_persists_publication_status_events() -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))
    run = store.create({"issue": "Publish me"})

    publishing = store.mark_publication_status(
        run.run_id,
        "publishing",
        event_type="run.publication_started",
        event_metadata={"mode": "pr"},
    )
    published = store.mark_publication_status(
        run.run_id,
        "published",
        event_type="run.publication_published",
        event_metadata={"mode": "pr", "pr_url": "https://github.com/octo/repo/pull/1"},
    )

    assert publishing.publication_status == "publishing"
    assert published.publication_status == "published"
    assert [event["event_type"] for event in published.events] == [
        "run.created",
        "run.queued",
        "run.publication_started",
        "run.publication_published",
    ]
    assert published.events[-1]["metadata"]["pr_url"] == "https://github.com/octo/repo/pull/1"


def test_sql_run_store_lists_recent_runs_for_owner() -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))
    octo = RunOwner(github_user_id=101, github_login="octo")
    mona = RunOwner(github_user_id=202, github_login="mona")
    first = store.create({"issue": "First"}, owner=octo)
    second = store.create({"issue": "Second"}, owner=mona)
    third = store.create({"issue": "Third"}, owner=octo)

    all_runs = store.list()
    octo_runs = store.list(owner=octo)

    assert [run.run_id for run in all_runs] == [third.run_id, second.run_id, first.run_id]
    assert [run.run_id for run in octo_runs] == [third.run_id, first.run_id]
