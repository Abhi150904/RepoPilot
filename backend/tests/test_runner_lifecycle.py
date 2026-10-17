from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine

from app import cli
from app.api.runs import RunStore
from app.core.config import Settings, deployment_issues
from app.services import runner_lifecycle as lifecycle


VM_ID = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/repopilot/providers/Microsoft.Compute/virtualMachines/repopilot-runner"


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class VM:
    def __init__(self, states):
        self.states = iter(states)
        self.state = "running"
        self.actions = []

    def power_state(self):
        self.state = next(self.states, self.state)
        return self.state

    def start(self):
        self.actions.append("start")

    def deallocate(self):
        self.actions.append("deallocate")


def controller(vm, clock, **kwargs):
    return lifecycle.RunnerLifecycle(vm, ready=lambda: True, clock=clock, sleep=clock.sleep,
                                    idle_seconds=60, boot_timeout=30, **kwargs)


def test_starts_once_and_waits_for_power_and_docker():
    clock = Clock()
    vm = VM(["deallocated", "deallocated", "starting", "running", "running"])
    runner = controller(vm, clock)
    checks = iter([False, True])
    runner.ready = lambda: next(checks)
    assert runner.tick(True)
    # Deallocated observations should not reset the action throttle.
    assert vm.actions == ["start"]
    assert clock.now == 20


def test_never_claims_when_ssh_or_image_is_unavailable():
    clock = Clock()
    vm = VM(["running"])
    runner = controller(vm, clock)
    runner.ready = lambda: False
    with pytest.raises(lifecycle.RunnerUnavailable, match="still preparing"):
        runner.tick(True)
    assert vm.actions == []


def test_idle_grace_resets_after_work_and_does_not_stop_active_work():
    clock = Clock()
    vm = VM(["running"])
    runner = controller(vm, clock)
    assert not runner.tick(False)
    clock.sleep(59)
    assert not runner.tick(False)
    assert runner.tick(True)
    clock.sleep(1000)
    assert runner.tick(True)
    assert vm.actions == []
    runner.tick(False)
    clock.sleep(60)
    runner.tick(False)
    assert vm.actions == ["deallocate"]


def test_arrival_during_shutdown_waits_for_deallocation_before_restart(tmp_path):
    clock = Clock()
    marker = tmp_path / "runner.deallocating"
    vm = VM(["running", "running", "deallocating", "deallocated", "starting", "running"])
    runner = controller(vm, clock, shutdown_marker=marker)
    runner.tick(False)
    clock.sleep(60)
    runner.tick(False)
    assert marker.exists()
    # Restarting the worker cannot forget an already accepted shutdown.
    restarted = controller(vm, clock, shutdown_marker=marker)
    assert restarted.tick(True)
    assert not marker.exists()
    assert vm.actions[-1] == "start"
    assert "deallocate" in vm.actions


def test_no_cloud_call_while_idle_grace_is_running():
    runner = controller(SimpleNamespace(), Clock())
    assert not runner.tick(False)


def test_stopped_but_allocated_is_deallocated():
    clock = Clock()
    vm = VM(["stopped"])
    runner = controller(vm, clock)
    runner.tick(False)
    clock.sleep(60)
    runner.tick(False)
    assert vm.actions == ["deallocate"]


@pytest.mark.parametrize("sql", [False, True])
def test_queue_query_includes_other_owners_and_running_jobs(sql):
    store = RunStore(engine=create_engine("sqlite:///:memory:")) if sql else RunStore()
    try:
        assert not store.has_unfinished_runs()
        run = store.create({"issue": "test"})
        assert store.has_unfinished_runs()
        store.claim_next_queued()
        assert store.has_unfinished_runs()
        store.mark_failed(run.run_id, RuntimeError("failed"))
        assert not store.has_unfinished_runs()
    finally:
        store.close()


def test_worker_does_not_claim_until_runner_is_ready(monkeypatch):
    from contextlib import contextmanager

    events = []

    @contextmanager
    def managed(_):
        def tick(work):
            events.append(("ready", work))
            return True
        yield SimpleNamespace(tick=tick)

    monkeypatch.setattr(cli, "runner_controller", managed)
    run = object()
    worker = SimpleNamespace(
        run_store=SimpleNamespace(has_unfinished_runs=lambda: True),
        execute_next_queued=lambda: events.append("claim") or run,
    )
    assert cli._worker_loop(service=worker, poll_interval=2, max_runs=1) == [run]
    assert events == [("ready", True), "claim"]


def test_infrastructure_failure_retries_without_claiming_or_logging_secrets(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(cli.time, "sleep", calls.append)

    def execute():
        if not calls:
            raise lifecycle.RunnerUnavailable("Runner unavailable.")
        return "done"

    assert cli._poll_worker(execute_next=execute, recover=lambda: None,
                            poll_interval=2, max_runs=1) == ["done"]
    assert calls == [30]


def test_arm_uses_fixed_endpoints_cached_identity_and_only_target_vm():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "169.254.169.254":
            assert request.headers["Metadata"] == "true"
            return httpx.Response(200, json={"access_token": "SECRET", "expires_on": "9999999999"})
        assert request.headers["Authorization"] == "Bearer SECRET"
        assert request.url.path.startswith(VM_ID)
        if request.method == "POST":
            return httpx.Response(202)
        return httpx.Response(200, json={"statuses": [{"code": "PowerState/deallocated"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        vm = lifecycle.AzureRunnerVM(VM_ID, client=client)
        assert vm.power_state() == "deallocated"
        vm.start()
        vm.deallocate()
    assert len(requests) == 4
    assert [r.url.path.rsplit("/", 1)[-1] for r in requests[1:]] == ["instanceView", "start", "deallocate"]


@pytest.mark.parametrize("status", [401, 403, 409, 429, 500])
def test_cloud_error_body_is_not_exposed(status):
    def handler(request):
        if request.url.host == "169.254.169.254":
            return httpx.Response(200, json={"access_token": "SECRET", "expires_on": "9999999999"})
        return httpx.Response(status, text="SECRET_CLOUD_ERROR")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(lifecycle.RunnerUnavailable) as error:
            lifecycle.AzureRunnerVM(VM_ID, client=client).power_state()
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("value", [None, "https://evil.invalid", VM_ID + "/start", VM_ID + "?redirect=evil"])
def test_rejects_invalid_vm_target(value):
    assert not lifecycle.valid_vm_resource_id(value)


def test_automation_config_requires_isolated_durable_worker():
    settings = Settings(_env_file=None, azure_runner_enabled=True)
    issues = deployment_issues(settings)
    assert any("resource ID" in issue for issue in issues)
    assert any("durable database" in issue for issue in issues)
    assert any("inline execution" in issue for issue in issues)


def test_docker_probe_is_remote_bounded_and_checks_prebuilt_image(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(lifecycle.subprocess, "run", run)
    assert lifecycle.docker_ready("ssh://sandbox@sandbox-runner", "repopilot-sandbox:aws")
    assert seen["command"][:3] == ["docker", "--host", "ssh://sandbox@sandbox-runner"]
    assert seen["timeout"] == 15
    assert seen["command"][-1] == "repopilot-sandbox:aws"


def test_no_claim_while_runner_is_unavailable(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def managed(_):
        yield SimpleNamespace(tick=lambda _: False)

    monkeypatch.setattr(cli, "runner_controller", managed)
    worker = SimpleNamespace(
        run_store=SimpleNamespace(has_unfinished_runs=lambda: True),
        execute_next_queued=lambda: pytest.fail("Run claimed before Docker readiness"),
    )
    assert cli._worker_loop(service=worker, poll_interval=2, max_runs=1) == []


def test_ambiguous_deallocation_error_persists_intent(tmp_path):
    clock = Clock()
    marker = tmp_path / "runner.deallocating"
    vm = VM(["running"])

    def deallocate():
        raise lifecycle.RunnerUnavailable("Request timed out.")

    vm.deallocate = deallocate
    runner = controller(vm, clock, shutdown_marker=marker)
    runner.tick(False)
    clock.sleep(60)
    with pytest.raises(lifecycle.RunnerUnavailable):
        runner.tick(False)
    assert marker.exists()
    # It must not assume a running response means the timed-out stop was rejected.
    with pytest.raises(lifecycle.RunnerUnavailable):
        runner.tick(True)


def test_controller_refuses_second_worker(monkeypatch, tmp_path):
    import sys

    def flock(*_):
        raise BlockingIOError()

    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=flock))
    settings = Settings(_env_file=None, azure_runner_enabled=True, azure_runner_resource_id=VM_ID,
                        sandbox_docker_host="ssh://sandbox@sandbox-runner",
                        azure_runner_lock_path=str(tmp_path / "runner.lock"))
    with pytest.raises(SystemExit, match="already holds"):
        with lifecycle.runner_controller(settings):
            pytest.fail("Duplicate worker accepted")


@pytest.mark.parametrize("command", ["run-once", "eval-once", "eval-run"])
def test_automation_rejects_other_worker_commands(command, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(azure_runner_enabled=True))
    with pytest.raises(SystemExit, match="single continuous"):
        cli._run_worker_command(SimpleNamespace(worker_command=command))


def test_cost_estimate_includes_persistent_resources_and_does_not_promise_four_months():
    from pathlib import Path
    import runpy

    calculator = runpy.run_path(str(Path(__file__).resolve().parents[2] / "deploy" / "estimate_azure_cost.py"))
    result = calculator["estimate"](vm_hourly=.0246, disk_monthly=2.64, ip_hourly=.005,
                                    months=4, runner_hours=20, public_ips=2,
                                    other_monthly=3, remaining_usd=100)
    assert result["monthly_usd"] == 34.03
    assert result["period_usd"] == 136.12
    assert result["headroom_usd"] == -36.12
    assert result["fits_with_15_percent_reserve"] is False
