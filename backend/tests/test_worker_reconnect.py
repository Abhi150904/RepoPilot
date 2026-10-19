from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from app import cli


def disconnected():
    return OperationalError("SECRET_DATABASE_URL", {}, Exception("SECRET_PASSWORD"), connection_invalidated=True)


@pytest.mark.parametrize("loop", [cli._worker_loop, cli._eval_worker_loop])
def test_workers_recover_from_connection_loss_without_logging_secrets(loop, monkeypatch, caplog):
    sleeps = []
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)
    run = SimpleNamespace(run_id="run-1", id="eval-1")

    class Worker:
        calls = 0

        def execute_next_queued(self):
            self.calls += 1
            if self.calls <= 2:
                raise disconnected()
            return run

    worker = Worker()
    assert loop(service=worker, poll_interval=2, max_runs=1) == [run]
    assert sleeps == [1, 2]
    assert "retrying queue polling" in caplog.text
    assert "SECRET" not in caplog.text


def test_initial_recovery_connection_failure_is_retried(monkeypatch):
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    calls = []

    def recover():
        calls.append(True)
        if len(calls) == 1:
            raise disconnected()

    assert cli._poll_worker(execute_next=lambda: None, recover=recover, poll_interval=2, max_runs=1) == []
    assert len(calls) == 2


def test_reconnect_delay_is_capped_and_ctrl_c_still_stops(monkeypatch):
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 8:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", sleep)

    def claim():
        raise disconnected()

    assert cli._poll_worker(execute_next=claim, recover=lambda: None, poll_interval=2, max_runs=None) == []
    assert sleeps == [1, 2, 4, 8, 16, 30, 30, 30]


def test_programming_and_authentication_errors_are_not_retried():
    for error in [ProgrammingError("bad SQL", {}, Exception()), OperationalError("connect", {}, SimpleNamespace(sqlstate="28P01"))]:
        def claim():
            raise error

        with pytest.raises(type(error)):
            cli._poll_worker(execute_next=claim, recover=lambda: None, poll_interval=2, max_runs=1)
