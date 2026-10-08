from __future__ import annotations

from app.core.config import Settings, inline_run_execution_enabled, readiness_report


def test_inline_run_execution_defaults_to_local_enabled() -> None:
    settings = Settings(hosted_mode=False, inline_run_execution=None, _env_file=None)

    assert inline_run_execution_enabled(settings) is True


def test_inline_run_execution_defaults_to_hosted_disabled() -> None:
    settings = Settings(hosted_mode=True, inline_run_execution=None, _env_file=None)

    assert inline_run_execution_enabled(settings) is False


def test_inline_run_execution_can_be_explicitly_enabled() -> None:
    settings = Settings(hosted_mode=True, inline_run_execution=True, _env_file=None)

    assert inline_run_execution_enabled(settings) is True


def test_hosted_readiness_requires_worker_queue_database() -> None:
    settings = Settings(hosted_mode=True, database_url=None, inline_run_execution=None, _env_file=None)

    report = readiness_report(settings)

    assert report["status"] == "degraded"
    assert report["checks"]["database_configured"] is False
    assert report["checks"]["worker_queue_configured"] is False
