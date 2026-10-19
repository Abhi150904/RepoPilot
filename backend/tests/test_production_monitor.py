import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "production_monitor", Path(__file__).resolve().parents[2] / "deploy" / "monitor_production.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


@pytest.mark.parametrize("probe, expected", [
    ({"oldest_queue_seconds": 0, "stale_running": 0}, True),
    ({"oldest_queue_seconds": 1200, "stale_running": 0}, True),
    ({"oldest_queue_seconds": 1201, "stale_running": 0}, False),
    ({"oldest_queue_seconds": 0, "stale_running": 1}, False),
    ({"oldest_queue_seconds": -1, "stale_running": 0}, False),
])
def test_queue_thresholds(probe, expected):
    assert monitor.queue_is_healthy(probe) is expected


def setup_checks(monkeypatch, *, stopped=None, health="healthy", queue=None, free=26 * 1024**3):
    def command(args, timeout=20):
        if args[1] == "inspect":
            service = args[-1].removeprefix("repopilot-aws-").removesuffix("-1")
            return {"Running": service != stopped, "Health": {"Status": health}}
        return queue or {"oldest_queue_seconds": 0, "stale_running": 0}
    monkeypatch.setattr(monitor, "command_json", command)
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda _: SimpleNamespace(
        total=30 * 1024**3, used=30 * 1024**3 - free, free=free))
    monkeypatch.setattr(monitor, "request", lambda *a, **kw: None)


def test_all_probes_healthy(monkeypatch):
    setup_checks(monkeypatch)
    assert all(monitor.check_production().values())


@pytest.mark.parametrize("service", monitor.SERVICES)
def test_each_stopped_service_fails(monkeypatch, service):
    setup_checks(monkeypatch, stopped=service)
    assert monitor.check_production()[service] is False


def test_unhealthy_containers_and_low_disk(monkeypatch):
    setup_checks(monkeypatch, health="unhealthy", free=1024**3)
    checks = monitor.check_production()
    assert not checks["api"] and not checks["database"]
    assert not checks["root_disk"] and not checks["workspace_disk"]


def test_probe_exceptions_fail_closed_without_secrets(monkeypatch, capsys):
    setup_checks(monkeypatch)
    def fail(*a, **kw):
        raise RuntimeError("PRIVATE-CREDENTIAL")
    monkeypatch.setattr(monitor, "command_json", fail)
    monkeypatch.setattr(monitor, "request", fail)
    assert monitor.main(["--check-only"]) == 1
    assert "PRIVATE-CREDENTIAL" not in str(capsys.readouterr())


@pytest.mark.parametrize("healthy, suffix, code", [(True, "", 0), (False, "/fail", 1)])
def test_heartbeat_reports_actual_health(monkeypatch, healthy, suffix, code):
    calls = []
    monkeypatch.setattr(monitor, "check_production", lambda: {"worker": healthy})
    monkeypatch.setattr(monitor, "load_ping_url", lambda: "https://hc-ping.com/private")
    monkeypatch.setattr(monitor, "request", lambda url: calls.append(url))
    assert monitor.main([]) == code
    assert calls == ["https://hc-ping.com/private" + suffix]


def test_delivery_failure_redacts_url(monkeypatch, capsys):
    monkeypatch.setattr(monitor, "check_production", lambda: {"worker": True})
    monkeypatch.setattr(monitor, "load_ping_url", lambda: "https://hc-ping.com/SECRET")
    def fail(url):
        raise ValueError(url)
    monkeypatch.setattr(monitor, "request", fail)
    assert monitor.main([]) == 2
    assert "SECRET" not in str(capsys.readouterr())


def test_check_only_never_reads_ping_secret(monkeypatch):
    monkeypatch.setattr(monitor, "check_production", lambda: {"worker": True})
    def fail():
        raise AssertionError("Should not load URL")
    monkeypatch.setattr(monitor, "load_ping_url", fail)
    assert monitor.main(["--check-only"]) == 0


@pytest.mark.parametrize("url", [
    "http://hc-ping.com/00000000-0000-0000-0000-000000000001",
    "https://example.com/00000000-0000-0000-0000-000000000001",
    "https://hc-ping.com/not-a-uuid",
    "https://hc-ping.com/00000000-0000-0000-0000-000000000001?secret=x",
])
def test_invalid_ping_urls_rejected(url):
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=0o100600, st_uid=0),
                           read_text=lambda: url)
    with pytest.raises(ValueError):
        monitor.load_ping_url(path)


def test_private_ping_url_file_required():
    for mode, uid in [(0o100644, 0), (0o120600, 0), (0o100600, 1000)]:
        path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=mode, st_uid=uid))
        with pytest.raises(ValueError):
            monitor.load_ping_url(path)


def test_canonical_ping_url_accepted():
    url = "https://hc-ping.com/00000000-0000-0000-0000-000000000001"
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=0o100600, st_uid=0),
                           read_text=lambda: url + "\n")
    assert monitor.load_ping_url(path) == url


@pytest.mark.parametrize("age, stale", [(30, 0), (1201, 0), (30, 1)])
def test_embedded_queue_probe_is_read_only_and_aggregate(monkeypatch, capsys, age, stale):
    import json
    from datetime import datetime, timedelta, timezone
    import sqlalchemy
    from sqlalchemy.dialects import postgresql
    from app.core import config

    statements = []
    values = iter([datetime.now(timezone.utc) - timedelta(seconds=age), stale])
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def scalar(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return next(values)

    engine = SimpleNamespace(connect=lambda: Connection(), dispose=lambda: None)
    def create_engine(url, connect_args):
        assert url == "postgresql+psycopg://unused"
        assert connect_args["connect_timeout"] == 5
        assert "statement_timeout=10000" in connect_args["options"]
        return engine

    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        database_url="postgresql+psycopg://unused"))
    exec(compile(monitor.QUEUE_PROBE, "<queue-probe>", "exec"), {})
    result = json.loads(capsys.readouterr().out)
    assert abs(result["oldest_queue_seconds"] - age) < 5
    assert result["stale_running"] == stale
    assert len(statements) == 2
    assert all(sql.startswith("SELECT ") for sql in statements)
    assert set(result) == {"oldest_queue_seconds", "stale_running"}
