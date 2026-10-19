import pytest
from pydantic import ValidationError

from app.core.config import Settings, deployment_issues, staging_user_allowed
from app.graph.workflow import _test_runner_for_workspace
from app.services.run_service import _test_runner_for_request
from app.api.schemas import RunRequest


def test_staging_ids_use_numeric_identity_and_deny_empty_list():
    settings = Settings(_env_file=None, deployment_environment="staging", staging_github_user_ids=" 101, 202 ")
    assert staging_user_allowed(settings, 101)
    assert not staging_user_allowed(settings, 999)
    settings.staging_github_user_ids = ""
    assert not staging_user_allowed(settings, 101)


@pytest.mark.parametrize("value", ["demo-user", "-1", "0", "101,user"])
def test_staging_ids_reject_usernames_and_invalid_ids(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, staging_github_user_ids=value)


def test_insecure_staging_configuration_is_reported():
    issues = deployment_issues(Settings(_env_file=None, deployment_environment="staging"))
    assert "Staging requires hosted mode." in issues
    assert any("HTTPS" in issue for issue in issues)


def test_staging_does_not_downgrade_npm_to_host_execution(tmp_path, monkeypatch):
    import app.graph.workflow as workflow
    import app.services.run_service as service

    settings = Settings(_env_file=None, hosted_mode=True, deployment_environment="staging")
    monkeypatch.setattr(workflow, "get_settings", lambda: settings)
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}')
    assert _test_runner_for_workspace(str(tmp_path), "docker", ["npm", "test"]) == "docker"
    assert _test_runner_for_request(RunRequest(issue="Test", test_runner="local")) == "docker"
